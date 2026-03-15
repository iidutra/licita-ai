"""Celery tasks — AI analysis."""
import logging

from celery import shared_task

from apps.opportunities.models import Opportunity, OpportunityDocument

logger = logging.getLogger(__name__)

# Maximum number of poll retries before giving up on documents and proceeding.
_DOC_POLL_MAX = 40  # 40 * 10s = ~6-7 min max wait
_DOC_POLL_DELAY = 10  # seconds between polls


def _refresh_document_list(opp: Opportunity):
    """Fetch fresh document list from PNCP API and create any missing records."""
    try:
        from apps.connectors.pncp import PNCPConnector

        raw = opp.raw_data or {}
        cnpj = raw.get("orgaoEntidadeCnpj", "") or opp.entity_cnpj or ""
        ano = raw.get("anoCompraPncp", "") or raw.get("anoCompra", "")
        seq = raw.get("sequencialCompraPncp", "") or raw.get("sequencialCompra", "")

        if not all([cnpj, ano, seq]):
            return

        connector = PNCPConnector()
        try:
            fresh_docs = connector.fetch_documents_fresh(cnpj, str(ano), str(seq))
        finally:
            connector.close()

        existing_urls = set(opp.documents.values_list("original_url", flat=True))
        created = 0
        for doc_data in fresh_docs:
            url = doc_data.get("url", "")
            if url and url not in existing_urls:
                OpportunityDocument.objects.create(
                    opportunity=opp,
                    original_url=url,
                    file_name=doc_data.get("file_name", "")[:500],
                    doc_type=doc_data.get("doc_type", "")[:100],
                )
                created += 1

        if created:
            logger.info("Refreshed docs for %s: %d new documents found", opp.pk, created)
    except Exception:
        logger.warning("Failed to refresh document list for %s", opp.pk, exc_info=True)


def _requeue_stuck_documents(opp: Opportunity) -> int:
    """Re-queue failed/pending/stuck docs. Returns total doc count."""
    from apps.opportunities.tasks import download_single_document, extract_document_text

    # First, check PNCP API for any new documents not yet in the DB
    _refresh_document_list(opp)

    docs = opp.documents.all()
    if not docs.exists():
        return 0

    # Re-queue documents stuck in non-terminal states
    requeue_statuses = [
        OpportunityDocument.ProcessingStatus.PENDING,
        OpportunityDocument.ProcessingStatus.FAILED,
        OpportunityDocument.ProcessingStatus.DOWNLOADING,
    ]
    for doc in docs.filter(processing_status__in=requeue_statuses):
        if doc.original_url:
            doc.processing_status = OpportunityDocument.ProcessingStatus.PENDING
            doc.error_message = ""
            doc.save(update_fields=["processing_status", "error_message", "updated_at"])
            download_single_document.delay(str(doc.pk))
            logger.info("Re-queued download for document %s", doc.pk)

    # Re-queue documents that were downloaded but never extracted
    for doc in docs.filter(processing_status=OpportunityDocument.ProcessingStatus.DOWNLOADED):
        extract_document_text.delay(str(doc.pk))
        logger.info("Re-queued extraction for document %s", doc.pk)

    return docs.count()


def _docs_ready(opp: Opportunity) -> tuple[bool, int]:
    """Check if all documents reached a terminal state (indexed or failed).

    Returns (all_done, indexed_count).
    """
    docs = opp.documents.all()
    total = docs.count()
    if total == 0:
        return True, 0

    indexed = docs.filter(
        processing_status=OpportunityDocument.ProcessingStatus.INDEXED
    ).count()
    failed = docs.filter(
        processing_status=OpportunityDocument.ProcessingStatus.FAILED
    ).count()

    return (indexed + failed >= total), indexed


@shared_task(bind=True, queue="ai", max_retries=2, default_retry_delay=30,
             soft_time_limit=600, time_limit=660)
def run_ai_analysis(self, opportunity_id: str, analysis_type: str = "full",
                    _doc_poll_count: int = 0):
    """Run AI analysis on an opportunity.

    Uses non-blocking polling for document readiness: instead of sleeping
    in a loop (which blocks the worker), the task re-enqueues itself with
    a short countdown when documents are not yet ready.
    """
    try:
        opp = Opportunity.objects.get(pk=opportunity_id)
    except Opportunity.DoesNotExist:
        logger.error("Opportunity %s not found", opportunity_id)
        return

    # Update status (only on the first call, not on poll retries)
    if _doc_poll_count == 0:
        if opp.status == Opportunity.Status.NEW:
            opp.status = Opportunity.Status.ANALYZING
            opp.save(update_fields=["status", "updated_at"])

        # Kick off any stuck documents
        total_docs = _requeue_stuck_documents(opp)
        if total_docs == 0:
            # No documents at all — skip straight to analysis
            return _run_analysis(self, opp, analysis_type, indexed_count=0)

    # Check if documents are ready (non-blocking)
    all_done, indexed_count = _docs_ready(opp)

    if not all_done and _doc_poll_count < _DOC_POLL_MAX:
        # Re-enqueue with countdown instead of blocking with time.sleep
        logger.info(
            "Documents not ready for %s (poll %d/%d), re-enqueuing in %ds",
            opp.pk, _doc_poll_count + 1, _DOC_POLL_MAX, _DOC_POLL_DELAY,
        )
        run_ai_analysis.apply_async(
            args=[opportunity_id, analysis_type],
            kwargs={"_doc_poll_count": _doc_poll_count + 1},
            countdown=_DOC_POLL_DELAY,
        )
        return

    if not all_done:
        logger.warning(
            "Document polling timed out for %s after %d polls, proceeding anyway",
            opp.pk, _doc_poll_count,
        )

    return _run_analysis(self, opp, analysis_type, indexed_count)


def _run_analysis(self, opp: Opportunity, analysis_type: str, indexed_count: int):
    """Execute the actual AI analysis (extraction + summary)."""
    if indexed_count == 0 and opp.documents.exists():
        logger.warning(
            "No indexed documents for %s, proceeding with metadata only",
            opp.pk,
        )

    previous_status = opp.status

    try:
        from .rag import run_extraction, run_summary

        if analysis_type in ("full", "checklist", "risks"):
            run_extraction(opp)

        if analysis_type in ("full", "summary"):
            run_summary(opp)

        logger.info("AI analysis '%s' complete for %s", analysis_type, opp.pk)

        # Notify
        from apps.notifications.tasks import create_notification
        create_notification.delay(
            event_type="ai_complete",
            subject=f"Análise IA concluída: {opp.title[:80]}",
            body=f"Análise tipo '{analysis_type}' finalizada para oportunidade {opp.number or opp.pk}.",
            opportunity_id=str(opp.pk),
        )

        return {"status": "success", "opportunity_id": str(opp.pk)}

    except Exception as exc:
        logger.exception("AI analysis failed for %s", opp.pk)
        # Revert status if all retries exhausted
        if self.request.retries >= self.max_retries:
            opp.status = previous_status
            opp.save(update_fields=["status", "updated_at"])
            logger.warning("Reverted status for %s to %s", opp.pk, previous_status)
        raise self.retry(exc=exc)
