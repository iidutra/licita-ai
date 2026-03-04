"""Celery tasks — ingestion from PNCP and Compras.gov."""
import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

from .normalizer import persist_opportunity
from .pncp import PNCPConnector, ALL_MODALITIES
from .compras_gov import ComprasGovConnector

logger = logging.getLogger(__name__)


@shared_task(bind=True, queue="ingest", max_retries=3, default_retry_delay=120)
def ingest_pncp(
    self,
    days_back: int = 3,
    uf: str | None = None,
    keyword: str | None = None,
    all_modalities: bool = True,
):
    """Ingest opportunities from PNCP for the given period."""
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)

    modalities = ALL_MODALITIES if all_modalities else None

    logger.info("PNCP ingestion: %s to %s (uf=%s, kw=%s, mods=%s)", date_from, date_to, uf, keyword, modalities)

    try:
        with PNCPConnector() as connector:
            opportunities = connector.fetch_opportunities(
                date_from=date_from,
                date_to=date_to,
                uf=uf,
                keyword=keyword,
                modalities=modalities,
            )

            created_count = 0
            for norm_opp in opportunities:
                try:
                    norm_opp.items = connector.fetch_items(norm_opp)
                except Exception:
                    logger.warning("Failed to fetch items for %s", norm_opp.external_id)
                try:
                    norm_opp.document_urls = connector.fetch_documents(norm_opp)
                except Exception:
                    logger.warning("Failed to fetch docs for %s", norm_opp.external_id)

                try:
                    opp, created = persist_opportunity(norm_opp)
                    if created:
                        created_count += 1
                        from apps.opportunities.tasks import download_opportunity_documents
                        download_opportunity_documents.delay(str(opp.pk))
                except Exception:
                    logger.warning("Failed to persist %s", norm_opp.external_id, exc_info=True)

            logger.info("PNCP ingestion complete: %d new / %d total", created_count, len(opportunities))
            return {"total": len(opportunities), "created": created_count}

    except Exception as exc:
        logger.exception("PNCP ingestion failed")
        raise self.retry(exc=exc)


@shared_task(bind=True, queue="ingest", max_retries=3, default_retry_delay=120)
def ingest_compras_gov(self, days_back: int = 1):
    """Ingest opportunities from Compras.gov.br."""
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)

    logger.info("Compras.gov ingestion: %s to %s", date_from, date_to)

    try:
        with ComprasGovConnector() as connector:
            opportunities = connector.fetch_opportunities(
                date_from=date_from,
                date_to=date_to,
            )

            created_count = 0
            for norm_opp in opportunities:
                norm_opp.document_urls = connector.fetch_documents(norm_opp)

                opp, created = persist_opportunity(norm_opp)
                if created:
                    created_count += 1
                    from apps.opportunities.tasks import download_opportunity_documents
                    download_opportunity_documents.delay(str(opp.pk))

            logger.info(
                "Compras.gov ingestion complete: %d new / %d total",
                created_count, len(opportunities),
            )
            return {"total": len(opportunities), "created": created_count}

    except Exception as exc:
        logger.exception("Compras.gov ingestion failed")
        raise self.retry(exc=exc)


@shared_task(bind=True, queue="ingest", max_retries=2, default_retry_delay=300)
def monitor_pregoes(self, hours_back: int = 6):
    """
    Monitor PNCP procurements for changes.

    1. Fetch updated procurement IDs from PNCP CONSULTA API.
    2. Filter to only tracked opportunities (active, deadline not passed).
    3. For each: fetch detail, docs, results, atas → detect changes → persist events.
    4. Notify interested clients for each new event.
    """
    from apps.opportunities.models import Opportunity
    from .monitoring import detect_changes, persist_events, update_opportunity_from_fresh

    now = timezone.now()
    date_to = now.date()
    date_from = (now - timedelta(hours=hours_back)).date()
    # PNCP API returns 400 when dataInicial == dataFinal
    if date_from == date_to:
        date_from = date_to - timedelta(days=1)

    logger.info("Monitor pregões: checking updates from %s to %s", date_from, date_to)

    try:
        with PNCPConnector() as connector:
            # Phase 1: Discover which procurements were updated
            updated_items = connector.fetch_updated_procurement_ids(date_from, date_to)
            if not updated_items:
                logger.info("Monitor pregões: no updates found")
                return {"checked": 0, "events": 0}

            updated_ext_ids = {item["external_id"] for item in updated_items}

            # Phase 2: Filter to tracked opportunities
            active_statuses = [
                Opportunity.Status.NEW,
                Opportunity.Status.ANALYZING,
                Opportunity.Status.ELIGIBLE,
                Opportunity.Status.SUBMITTED,
            ]
            tracked = Opportunity.objects.filter(
                source=Opportunity.Source.PNCP,
                status__in=active_statuses,
                external_id__in=updated_ext_ids,
            ).filter(
                models_Q_deadline_or_none(now),
            )

            # Build lookup for cnpj/ano/seq from updated_items
            ext_id_to_parts = {
                item["external_id"]: item for item in updated_items
            }

            total_events = 0
            checked = 0

            # Phase 3: For each tracked opportunity, fetch fresh data and detect changes
            for opp in tracked:
                parts = ext_id_to_parts.get(opp.external_id)
                if not parts:
                    continue

                cnpj, ano, seq = parts["cnpj"], str(parts["ano"]), str(parts["seq"])

                try:
                    fresh_data = connector.fetch_opportunity_detail(cnpj, ano, seq)
                    if not fresh_data:
                        continue

                    fresh_docs = connector.fetch_documents_fresh(cnpj, ano, seq)
                    fresh_results = connector.fetch_results(cnpj, ano, seq)
                    fresh_atas = connector.fetch_atas(cnpj, ano, seq)

                    event_dicts = detect_changes(
                        opp, fresh_data, fresh_docs, fresh_results, fresh_atas,
                    )

                    if event_dicts:
                        created_events = persist_events(opp, event_dicts)
                        total_events += len(created_events)

                        # Persist new documents
                        from apps.opportunities.models import OpportunityEvent as OppEvent
                        for ev in event_dicts:
                            if ev["event_type"] == OppEvent.EventType.NEW_DOCUMENT and ev.get("raw_data", {}).get("url"):
                                _persist_new_document(opp, ev["raw_data"])

                        # Notify for each new event
                        from apps.notifications.tasks import notify_pregao_event
                        for event in created_events:
                            notify_pregao_event.delay(str(opp.pk), str(event.pk))

                    update_opportunity_from_fresh(opp, fresh_data, fresh_results, fresh_atas)
                    checked += 1

                except Exception:
                    logger.exception(
                        "Monitor pregões: error processing %s", opp.external_id,
                    )

            logger.info(
                "Monitor pregões complete: %d checked, %d events created",
                checked, total_events,
            )
            return {"checked": checked, "events": total_events}

    except Exception as exc:
        logger.exception("Monitor pregões failed")
        raise self.retry(exc=exc)


def models_Q_deadline_or_none(now):
    """Return Q filter: deadline > now OR deadline is null."""
    from django.db.models import Q
    return Q(deadline__gt=now) | Q(deadline__isnull=True)


def _persist_new_document(opportunity, doc_data: dict):
    """Create an OpportunityDocument for a newly detected document."""
    from apps.opportunities.models import OpportunityDocument

    url = doc_data.get("url", "")
    if not url:
        return

    if opportunity.documents.filter(original_url=url).exists():
        return

    OpportunityDocument.objects.create(
        opportunity=opportunity,
        original_url=url,
        file_name=doc_data.get("file_name", ""),
        doc_type=doc_data.get("doc_type", ""),
        processing_status=OpportunityDocument.ProcessingStatus.PENDING,
    )

    # Trigger download
    from apps.opportunities.tasks import download_opportunity_documents
    download_opportunity_documents.delay(str(opportunity.pk))
