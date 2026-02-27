"""Notification dispatchers: email and webhook."""
import logging

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import EventNotification

logger = logging.getLogger(__name__)


def send_email_notification(notification: EventNotification) -> bool:
    """Send an email notification."""
    if not notification.recipient:
        logger.warning("No recipient for notification %s", notification.id)
        return False
    try:
        send_mail(
            subject=notification.subject,
            message=notification.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient],
            fail_silently=False,
        )
        notification.delivery_status = EventNotification.DeliveryStatus.SENT
        notification.sent_at = timezone.now()
        notification.save(update_fields=["delivery_status", "sent_at", "updated_at"])
        return True
    except Exception as exc:
        notification.delivery_status = EventNotification.DeliveryStatus.FAILED
        notification.error_message = str(exc)
        notification.save(update_fields=["delivery_status", "error_message", "updated_at"])
        logger.exception("Email notification failed: %s", notification.id)
        return False


def send_webhook_notification(notification: EventNotification) -> bool:
    """Post JSON to a webhook URL."""
    url = notification.recipient or settings.WEBHOOK_URL
    if not url:
        logger.warning("No webhook URL for notification %s", notification.id)
        return False
    try:
        payload = {
            "event": notification.event_type,
            "subject": notification.subject,
            "body": notification.body,
            "payload": notification.payload,
            "timestamp": notification.created_at.isoformat(),
        }
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        notification.delivery_status = EventNotification.DeliveryStatus.SENT
        notification.sent_at = timezone.now()
        notification.save(update_fields=["delivery_status", "sent_at", "updated_at"])
        return True
    except Exception as exc:
        notification.delivery_status = EventNotification.DeliveryStatus.FAILED
        notification.error_message = str(exc)
        notification.save(update_fields=["delivery_status", "error_message", "updated_at"])
        logger.exception("Webhook notification failed: %s", notification.id)
        return False


def dispatch_notification(notification: EventNotification) -> bool:
    """Route notification to the correct channel."""
    if notification.channel == EventNotification.Channel.EMAIL:
        return send_email_notification(notification)
    elif notification.channel == EventNotification.Channel.WEBHOOK:
        return send_webhook_notification(notification)
    # INTERNAL = just stored in DB, shown in dashboard
    notification.delivery_status = EventNotification.DeliveryStatus.SENT
    notification.sent_at = timezone.now()
    notification.save(update_fields=["delivery_status", "sent_at", "updated_at"])
    return True
