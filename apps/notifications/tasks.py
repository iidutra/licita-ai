"""Celery tasks — notifications and alerts."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.clients.models import Client
from apps.opportunities.models import Opportunity

from .models import EventNotification
from .notifiers import dispatch_notification

logger = logging.getLogger(__name__)


@shared_task(queue="notifications")
def create_notification(
    event_type: str,
    subject: str,
    body: str,
    opportunity_id: str | None = None,
    client_id: str | None = None,
    channel: str = "internal",
    recipient: str = "",
):
    """Create and optionally dispatch a notification."""
    notif = EventNotification.objects.create(
        event_type=event_type,
        channel=channel,
        recipient=recipient,
        subject=subject,
        body=body,
        opportunity_id=opportunity_id,
        client_id=client_id,
    )

    # Auto-dispatch for email/webhook
    if channel != EventNotification.Channel.INTERNAL:
        dispatch_notification(notif)

    return str(notif.pk)


@shared_task(queue="notifications")
def check_critical_deadlines():
    """Check for opportunities with deadlines in the next 3 days."""
    threshold = timezone.now() + timedelta(days=3)
    upcoming = Opportunity.objects.filter(
        deadline__lte=threshold,
        deadline__gt=timezone.now(),
        status__in=[
            Opportunity.Status.NEW,
            Opportunity.Status.ANALYZING,
            Opportunity.Status.ELIGIBLE,
        ],
    )

    created = 0
    for opp in upcoming:
        days_left = (opp.deadline - timezone.now()).days

        # Only notify once per opportunity per deadline window
        exists = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            opportunity_id=opp.pk,
            created_at__gte=timezone.now() - timedelta(days=1),
        ).exists()
        if exists:
            continue

        # Notify all clients with high-score matches
        for match in opp.matches.filter(score__gte=60).select_related("client"):
            if match.client.notify_email and match.client.email:
                create_notification.delay(
                    event_type="deadline_warning",
                    subject=f"Prazo em {days_left} dias: {opp.title[:60]}",
                    body=(
                        f"A oportunidade '{opp.title[:100]}' encerra em {days_left} dia(s).\n"
                        f"Prazo: {opp.deadline.strftime('%d/%m/%Y %H:%M')}\n"
                        f"Seu score: {match.score}/100"
                    ),
                    opportunity_id=str(opp.pk),
                    client_id=str(match.client.pk),
                    channel="email",
                    recipient=match.client.email,
                )
                created += 1

        # Also create internal notification
        create_notification.delay(
            event_type="deadline_warning",
            subject=f"Prazo em {days_left} dias: {opp.title[:60]}",
            body=f"Oportunidade '{opp.title[:100]}' encerra em {opp.deadline.strftime('%d/%m/%Y %H:%M')}",
            opportunity_id=str(opp.pk),
        )
        created += 1

    logger.info("Deadline check: %d notifications created", created)
    return {"notifications_created": created}


@shared_task(queue="notifications")
def dispatch_pending_notifications():
    """Retry failed notifications."""
    pending = EventNotification.objects.filter(
        delivery_status=EventNotification.DeliveryStatus.PENDING,
    ).exclude(
        channel=EventNotification.Channel.INTERNAL
    )[:50]

    for notif in pending:
        dispatch_notification(notif)
