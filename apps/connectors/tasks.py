"""Celery tasks — ingestion from PNCP and Compras.gov."""
import logging
from datetime import date, timedelta

from celery import shared_task

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
