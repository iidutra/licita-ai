"""Celery tasks — AI analysis."""
import logging

from celery import shared_task

from apps.opportunities.models import Opportunity

logger = logging.getLogger(__name__)


@shared_task(bind=True, queue="ai", max_retries=2, default_retry_delay=30)
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
