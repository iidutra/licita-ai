"""Celery tasks — AI analysis."""
import logging
import time

from celery import shared_task

from apps.opportunities.models import Opportunity, OpportunityDocument

logger = logging.getLogger(__name__)


def _ensure_documents_indexed(opp: Opportunity, timeout: int = 300) -> int:
    """Re-queue failed/pending docs and wait until all are indexed (or timeout).

    Returns the number of indexed documents.
    """
    from apps.opportunities.tasks import download_single_document, extract_document_text

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

    # Wait for documents to be indexed
    deadline = time.time() + timeout
    poll_interval = 5
    while time.time() < deadline:
        total = docs.count()
        indexed = docs.filter(
            processing_status=OpportunityDocument.ProcessingStatus.INDEXED
        ).count()
        failed = docs.filter(
            processing_status=OpportunityDocument.ProcessingStatus.FAILED
        ).count()

        if indexed + failed >= total:
            break

        time.sleep(poll_interval)

    indexed_count = docs.filter(
        processing_status=OpportunityDocument.ProcessingStatus.INDEXED
    ).count()
    logger.info(
        "Document indexing for %s: %d/%d indexed",
        opp.pk, indexed_count, docs.count(),
    )
    return indexed_count


@shared_task(bind=True, queue="ai", max_retries=2, default_retry_delay=30,
             soft_time_limit=600, time_limit=660)
def run_ai_analysis(self, opportunity_id: str, analysis_type: str = "full"):
    """Run AI analysis on an opportunity."""
    try:
        opp = Opportunity.objects.get(pk=opportunity_id)
    except Opportunity.DoesNotExist:
        logger.error("Opportunity %s not found", opportunity_id)
        return

    # Update status
    previous_status = opp.status
    if opp.status == Opportunity.Status.NEW:
        opp.status = Opportunity.Status.ANALYZING
        opp.save(update_fields=["status", "updated_at"])

    try:
        # Ensure documents are indexed before running AI
        indexed = _ensure_documents_indexed(opp)
        if indexed == 0 and opp.documents.exists():
            logger.warning(
                "No indexed documents for %s, proceeding with metadata only",
                opp.pk,
            )

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
        logger.exception("AI analysis failed for %s", opportunity_id)
        # Revert status if all retries exhausted
        if self.request.retries >= self.max_retries:
            opp.status = previous_status
            opp.save(update_fields=["status", "updated_at"])
            logger.warning("Reverted status for %s to %s", opportunity_id, previous_status)
        raise self.retry(exc=exc)
