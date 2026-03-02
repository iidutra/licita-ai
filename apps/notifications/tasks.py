"""Celery tasks — notifications and alerts."""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
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


# ── Helper ─────────────────────────────────────────────────


def _notify_clients(opp: Opportunity, event_type: str, subject: str, body: str) -> int:
    """
    Notify all clients with high-score matches for an opportunity.

    Sends via email, WhatsApp, and internal channels.
    Returns the total number of notifications dispatched.
    """
    min_score = getattr(settings, "MONITORING_MIN_MATCH_SCORE", 60)
    matches = opp.matches.filter(score__gte=min_score).select_related("client")

    created = 0
    for match in matches:
        client = match.client

        if client.notify_email and client.email:
            create_notification.delay(
                event_type=event_type,
                subject=subject,
                body=body,
                opportunity_id=str(opp.pk),
                client_id=str(client.pk),
                channel="email",
                recipient=client.email,
            )
            created += 1

        if client.notify_whatsapp and getattr(client, "whatsapp_phone", ""):
            create_notification.delay(
                event_type=event_type,
                subject=subject,
                body=body,
                opportunity_id=str(opp.pk),
                client_id=str(client.pk),
                channel="whatsapp",
                recipient=client.whatsapp_phone,
            )
            created += 1

        # Internal notification always
        create_notification.delay(
            event_type=event_type,
            subject=subject,
            body=body,
            opportunity_id=str(opp.pk),
            client_id=str(client.pk),
        )
        created += 1

    return created


# ── Deadline warnings (progressive scale) ──────────────────


DEADLINE_WINDOWS = [
    (7, "Prazo em 7 dias"),
    (3, "Prazo em 3 dias"),
    (1, "Encerra AMANHA"),
    (0, "Encerra HOJE"),
]

ACTIVE_STATUSES = [
    Opportunity.Status.NEW,
    Opportunity.Status.ANALYZING,
    Opportunity.Status.ELIGIBLE,
    Opportunity.Status.SUBMITTED,
]


@shared_task(queue="notifications")
def check_critical_deadlines():
    """
    Check for opportunities approaching deadlines.

    Progressive scale: 7 days, 3 days, 1 day, today.
    Runs 2x/day. Dedup: 1 notification per opportunity per window per 20h.
    """
    now = timezone.now()
    created = 0

    for days, label in DEADLINE_WINDOWS:
        if days == 0:
            window_start = now
            window_end = now.replace(hour=23, minute=59, second=59)
        else:
            window_start = now + timedelta(days=days) - timedelta(hours=12)
            window_end = now + timedelta(days=days) + timedelta(hours=12)

        opps = Opportunity.objects.filter(
            deadline__gte=window_start,
            deadline__lt=window_end,
            status__in=ACTIVE_STATUSES,
        )

        for opp in opps:
            # Dedup: check if we already sent this window tag for this opp
            already_sent = EventNotification.objects.filter(
                event_type=EventNotification.EventType.DEADLINE_WARNING,
                opportunity_id=opp.pk,
                created_at__gte=now - timedelta(hours=20),
                payload__window_tag=f"deadline_{days}d",
            ).exists()
            if already_sent:
                continue

            deadline_fmt = opp.deadline.strftime("%d/%m/%Y %H:%M")
            subject = f"{label}: {opp.title[:60]}"
            body = (
                f"A oportunidade '{opp.title[:100]}' encerra em {deadline_fmt}.\n"
                f"Orgao: {opp.entity_name}\n"
                f"No: {opp.number}"
            )

            created += _notify_clients(opp, "deadline_warning", subject, body)

            # Internal notification with window tag for dedup
            EventNotification.objects.create(
                event_type=EventNotification.EventType.DEADLINE_WARNING,
                channel=EventNotification.Channel.INTERNAL,
                subject=subject,
                body=body,
                opportunity_id=opp.pk,
                delivery_status=EventNotification.DeliveryStatus.SENT,
                sent_at=now,
                payload={"window_tag": f"deadline_{days}d"},
            )
            created += 1

    logger.info("Deadline check: %d notifications created", created)
    return {"notifications_created": created}


# ── Proposals opening / Session today ──────────────────────


@shared_task(queue="notifications")
def check_proposals_opening():
    """
    Alert clients about proposal opening tomorrow and today.

    For pregao eletronico: uses SESSION_TODAY event type.
    For other modalities: uses PROPOSALS_OPENING event type.
    Runs 2x/day.
    """
    now = timezone.now()
    created = 0

    windows = [
        ("tomorrow", now + timedelta(hours=12), now + timedelta(hours=36)),
        ("today", now, now + timedelta(hours=12)),
    ]

    for window_name, start, end in windows:
        opps = Opportunity.objects.filter(
            proposals_open_at__gte=start,
            proposals_open_at__lt=end,
            status__in=[
                Opportunity.Status.NEW,
                Opportunity.Status.ANALYZING,
                Opportunity.Status.ELIGIBLE,
            ],
        )

        for opp in opps:
            is_pregao = opp.modality == Opportunity.Modality.PREGAO_ELETRONICO

            if is_pregao:
                event_type = "session_today"
                time_label = "AMANHA" if window_name == "tomorrow" else "HOJE"
                subject = f"Sessao publica {time_label}: {opp.title[:60]}"
                body = (
                    f"A sessao publica do pregao eletronico ocorre {time_label}.\n"
                    f"Abertura: {opp.proposals_open_at.strftime('%d/%m/%Y %H:%M')}\n"
                    f"Orgao: {opp.entity_name}\n"
                    f"No: {opp.number}"
                )
            else:
                event_type = "proposals_opening"
                time_label = "amanha" if window_name == "tomorrow" else "HOJE"
                subject = f"Propostas abrem {time_label}: {opp.title[:60]}"
                body = (
                    f"A abertura de propostas ocorre {time_label}.\n"
                    f"Abertura: {opp.proposals_open_at.strftime('%d/%m/%Y %H:%M')}\n"
                    f"Orgao: {opp.entity_name}\n"
                    f"No: {opp.number}"
                )

            # Dedup: 1 notification per opp + window per day
            already_sent = EventNotification.objects.filter(
                event_type=event_type,
                opportunity_id=opp.pk,
                created_at__gte=now - timedelta(hours=20),
                payload__window_tag=f"opening_{window_name}",
            ).exists()
            if already_sent:
                continue

            created += _notify_clients(opp, event_type, subject, body)

            EventNotification.objects.create(
                event_type=event_type,
                channel=EventNotification.Channel.INTERNAL,
                subject=subject,
                body=body,
                opportunity_id=opp.pk,
                delivery_status=EventNotification.DeliveryStatus.SENT,
                sent_at=now,
                payload={"window_tag": f"opening_{window_name}"},
            )
            created += 1

    logger.info("Proposals opening check: %d notifications created", created)
    return {"notifications_created": created}


# ── Session imminent (10 minutes before) ───────────────────


@shared_task(queue="notifications")
def check_session_imminent():
    """
    Alert clients 10 minutes before a pregao eletronico session starts.

    Runs every 5 minutes. Looks for sessions starting in the next 15 minutes.
    Only for pregao eletronico modality.
    """
    now = timezone.now()
    window_end = now + timedelta(minutes=15)

    opps = Opportunity.objects.filter(
        proposals_open_at__gte=now,
        proposals_open_at__lt=window_end,
        modality=Opportunity.Modality.PREGAO_ELETRONICO,
        status__in=ACTIVE_STATUSES,
    )

    created = 0
    for opp in opps:
        # Dedup: only once per opportunity (2h window)
        already_sent = EventNotification.objects.filter(
            event_type=EventNotification.EventType.SESSION_IMMINENT,
            opportunity_id=opp.pk,
            created_at__gte=now - timedelta(hours=2),
        ).exists()
        if already_sent:
            continue

        minutes_left = int((opp.proposals_open_at - now).total_seconds() / 60)
        subject = f"SESSAO EM {minutes_left} MIN: {opp.title[:60]}"
        body = (
            f"A sessao publica do pregao eletronico comeca em {minutes_left} minutos!\n"
            f"Horario: {opp.proposals_open_at.strftime('%d/%m/%Y %H:%M')}\n"
            f"Orgao: {opp.entity_name}\n"
            f"No: {opp.number}"
        )

        created += _notify_clients(opp, "session_imminent", subject, body)

        EventNotification.objects.create(
            event_type=EventNotification.EventType.SESSION_IMMINENT,
            channel=EventNotification.Channel.INTERNAL,
            subject=subject,
            body=body,
            opportunity_id=opp.pk,
            delivery_status=EventNotification.DeliveryStatus.SENT,
            sent_at=now,
        )
        created += 1

    if created:
        logger.info("Session imminent: %d notifications created", created)
    return {"notifications_created": created}


@shared_task(queue="notifications")
def notify_pregao_event(opportunity_id: str, event_id: str):
    """
    Notify interested clients about a pregão event.

    For each match with score >= MONITORING_MIN_MATCH_SCORE:
    - Email (if notify_email), WhatsApp (if notify_whatsapp), Internal
    """
    from django.conf import settings as conf
    from apps.opportunities.models import OpportunityEvent

    EVENT_TYPE_MAP = {
        OpportunityEvent.EventType.STATUS_CHANGE: "pregao_status_change",
        OpportunityEvent.EventType.NEW_DOCUMENT: "pregao_new_document",
        OpportunityEvent.EventType.RESULT_PUBLISHED: "pregao_result",
        OpportunityEvent.EventType.ATA_PUBLISHED: "pregao_result",
        OpportunityEvent.EventType.DEADLINE_CHANGED: "pregao_status_change",
        OpportunityEvent.EventType.VALUE_CHANGED: "pregao_status_change",
        OpportunityEvent.EventType.GENERAL_UPDATE: "pregao_status_change",
    }

    try:
        opp = Opportunity.objects.get(pk=opportunity_id)
        event = OpportunityEvent.objects.get(pk=event_id)
    except (Opportunity.DoesNotExist, OpportunityEvent.DoesNotExist):
        logger.warning("notify_pregao_event: opp=%s event=%s not found", opportunity_id, event_id)
        return

    notif_event_type = EVENT_TYPE_MAP.get(event.event_type, "pregao_status_change")
    subject = f"[{event.get_event_type_display()}] {opp.title[:60]}"
    body = (
        f"{event.description}\n\n"
        f"Oportunidade: {opp.title[:120]}\n"
        f"Órgão: {opp.entity_name}\n"
        f"Nº: {opp.number}"
    )

    min_score = conf.MONITORING_MIN_MATCH_SCORE
    matches = opp.matches.filter(score__gte=min_score).select_related("client")

    created = 0
    for match in matches:
        client = match.client

        # Dedup: skip if recent notification (1h) for same opp + event_type + client
        recent_exists = EventNotification.objects.filter(
            event_type=notif_event_type,
            opportunity_id=opp.pk,
            client_id=client.pk,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).exists()
        if recent_exists:
            continue

        if client.notify_email and client.email:
            create_notification.delay(
                event_type=notif_event_type,
                subject=subject,
                body=body,
                opportunity_id=str(opp.pk),
                client_id=str(client.pk),
                channel="email",
                recipient=client.email,
            )
            created += 1

        if client.notify_whatsapp and getattr(client, "whatsapp_phone", ""):
            create_notification.delay(
                event_type=notif_event_type,
                subject=subject,
                body=body,
                opportunity_id=str(opp.pk),
                client_id=str(client.pk),
                channel="whatsapp",
                recipient=client.whatsapp_phone,
            )
            created += 1

        # Internal notification always
        create_notification.delay(
            event_type=notif_event_type,
            subject=subject,
            body=body,
            opportunity_id=str(opp.pk),
            client_id=str(client.pk),
        )
        created += 1

    logger.info(
        "notify_pregao_event: opp=%s event=%s — %d notifications created",
        opportunity_id, event_id, created,
    )
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
