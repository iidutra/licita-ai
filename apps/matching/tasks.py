"""Celery tasks — matching."""
import logging

from celery import shared_task

from apps.clients.models import Client
from apps.opportunities.models import Opportunity

logger = logging.getLogger(__name__)


@shared_task(bind=True, queue="ai", max_retries=2, default_retry_delay=30)
def run_matching(self, opportunity_id: str, client_id: str):
    """Run matching between an opportunity and a client."""
    try:
        opp = Opportunity.objects.get(pk=opportunity_id)
        client = Client.objects.get(pk=client_id)
    except (Opportunity.DoesNotExist, Client.DoesNotExist) as exc:
        logger.error("Not found: opp=%s, client=%s", opportunity_id, client_id)
        return

    try:
        from .engine import run_matching as do_matching

        match = do_matching(opp, client)

        # Notify if high score
        if match.score >= 70:
            from apps.notifications.tasks import create_notification
            create_notification.delay(
                event_type="high_score_match",
                subject=f"Match alto ({match.score}/100): {client.name} ↔ {opp.title[:60]}",
                body=(
                    f"O cliente {client.name} obteve score {match.score}/100 "
                    f"para a oportunidade '{opp.title[:100]}'.\n\n"
                    f"Justificativa: {match.justification[:500]}"
                ),
                opportunity_id=str(opp.pk),
                client_id=str(client.pk),
            )

        return {"score": match.score, "match_id": str(match.pk)}

    except Exception as exc:
        logger.exception("Matching failed: opp=%s, client=%s", opportunity_id, client_id)
        raise self.retry(exc=exc)
