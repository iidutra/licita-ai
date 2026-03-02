"""Tests for notification tasks — deadlines, opening, session alerts."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.notifications.models import EventNotification
from apps.notifications.tasks import (
    check_critical_deadlines,
    check_proposals_opening,
    check_session_imminent,
)
from apps.opportunities.models import Opportunity


# ── Helpers ──────────────────────────────────────────────────


def _set_deadline(opp, days_from_now):
    """Set opportunity deadline to N days from now."""
    opp.deadline = timezone.now() + timedelta(days=days_from_now)
    opp.save(update_fields=["deadline"])


def _set_proposals_open(opp, hours_from_now):
    """Set proposals_open_at to N hours from now."""
    opp.proposals_open_at = timezone.now() + timedelta(hours=hours_from_now)
    opp.save(update_fields=["proposals_open_at"])


# ── Deadline notifications ───────────────────────────────────


class TestDeadlineNotifications:
    @patch("apps.notifications.tasks.create_notification.delay")
    def test_7_day_warning(self, mock_delay, opportunity_with_dates):
        """Opportunity with deadline in 7 days triggers a 7-day warning."""
        _set_deadline(opportunity_with_dates, 7)

        result = check_critical_deadlines()

        assert result["notifications_created"] > 0
        notif = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            payload__window_tag="deadline_7d",
        ).first()
        assert notif is not None
        assert "Prazo em 7 dias" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_3_day_warning(self, mock_delay, opportunity_with_dates):
        """Opportunity with deadline in 3 days triggers a 3-day warning."""
        _set_deadline(opportunity_with_dates, 3)

        result = check_critical_deadlines()

        assert result["notifications_created"] > 0
        notif = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            payload__window_tag="deadline_3d",
        ).first()
        assert notif is not None
        assert "Prazo em 3 dias" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_1_day_warning(self, mock_delay, opportunity_with_dates):
        """Opportunity with deadline tomorrow triggers a 1-day warning."""
        _set_deadline(opportunity_with_dates, 1)

        result = check_critical_deadlines()

        assert result["notifications_created"] > 0
        notif = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            payload__window_tag="deadline_1d",
        ).first()
        assert notif is not None
        assert "Encerra AMANHA" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_today_warning(self, mock_delay, opportunity_with_dates):
        """Opportunity with deadline today triggers a today warning."""
        # Set deadline to later today
        now = timezone.now()
        opportunity_with_dates.deadline = now.replace(hour=23, minute=0, second=0)
        opportunity_with_dates.save(update_fields=["deadline"])

        result = check_critical_deadlines()

        assert result["notifications_created"] > 0
        notif = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            payload__window_tag="deadline_0d",
        ).first()
        assert notif is not None
        assert "Encerra HOJE" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_no_duplicate_same_window(self, mock_delay, opportunity_with_dates):
        """Running the task twice should not create duplicate notifications."""
        _set_deadline(opportunity_with_dates, 3)

        result1 = check_critical_deadlines()
        result2 = check_critical_deadlines()

        # Second run should create 0 notifications (dedup)
        assert result1["notifications_created"] > 0
        assert result2["notifications_created"] == 0

        # Only one internal notification with this window tag
        count = EventNotification.objects.filter(
            event_type=EventNotification.EventType.DEADLINE_WARNING,
            opportunity_id=opportunity_with_dates.pk,
            payload__window_tag="deadline_3d",
        ).count()
        assert count == 1

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_no_alert_for_discarded(self, mock_delay, opportunity_with_dates):
        """Discarded opportunities should not generate deadline alerts."""
        opportunity_with_dates.status = Opportunity.Status.DISCARDED
        opportunity_with_dates.save(update_fields=["status"])
        _set_deadline(opportunity_with_dates, 3)

        result = check_critical_deadlines()

        assert result["notifications_created"] == 0


# ── Proposals opening ────────────────────────────────────────


class TestProposalsOpening:
    @patch("apps.notifications.tasks.create_notification.delay")
    def test_opening_tomorrow(self, mock_delay, opportunity_with_dates):
        """Opportunity with proposals opening tomorrow triggers alert."""
        _set_proposals_open(opportunity_with_dates, 24)

        result = check_proposals_opening()

        assert result["notifications_created"] > 0

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_opening_today(self, mock_delay, opportunity_with_dates):
        """Opportunity with proposals opening in a few hours triggers alert."""
        _set_proposals_open(opportunity_with_dates, 6)

        result = check_proposals_opening()

        assert result["notifications_created"] > 0

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_session_today_for_pregao(self, mock_delay, opportunity_with_dates):
        """Pregao eletronico uses session_today event type."""
        assert opportunity_with_dates.modality == Opportunity.Modality.PREGAO_ELETRONICO
        _set_proposals_open(opportunity_with_dates, 6)

        check_proposals_opening()

        # Should use session_today for pregao eletronico
        notif = EventNotification.objects.filter(
            event_type="session_today",
            opportunity_id=opportunity_with_dates.pk,
        ).first()
        assert notif is not None
        assert "Sessao publica" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_proposals_opening_for_non_pregao(self, mock_delay, opportunity_with_dates):
        """Non-pregao modality uses proposals_opening event type."""
        opportunity_with_dates.modality = Opportunity.Modality.CONCORRENCIA_ELETRONICA
        opportunity_with_dates.save(update_fields=["modality"])
        _set_proposals_open(opportunity_with_dates, 6)

        check_proposals_opening()

        notif = EventNotification.objects.filter(
            event_type="proposals_opening",
            opportunity_id=opportunity_with_dates.pk,
        ).first()
        assert notif is not None
        assert "Propostas abrem" in notif.subject


# ── Session imminent ─────────────────────────────────────────


class TestSessionImminent:
    @patch("apps.notifications.tasks.create_notification.delay")
    def test_alert_10_min_before(self, mock_delay, opportunity_with_dates):
        """Session starting in 10 minutes triggers session_imminent alert."""
        # Set proposals_open_at to 10 minutes from now
        opportunity_with_dates.proposals_open_at = timezone.now() + timedelta(minutes=10)
        opportunity_with_dates.save(update_fields=["proposals_open_at"])

        result = check_session_imminent()

        assert result["notifications_created"] > 0
        notif = EventNotification.objects.filter(
            event_type=EventNotification.EventType.SESSION_IMMINENT,
            opportunity_id=opportunity_with_dates.pk,
        ).first()
        assert notif is not None
        assert "SESSAO EM" in notif.subject

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_no_alert_for_non_pregao(self, mock_delay, opportunity_with_dates):
        """Concorrencia does not trigger session_imminent alert."""
        opportunity_with_dates.modality = Opportunity.Modality.CONCORRENCIA_ELETRONICA
        opportunity_with_dates.proposals_open_at = timezone.now() + timedelta(minutes=10)
        opportunity_with_dates.save(update_fields=["modality", "proposals_open_at"])

        result = check_session_imminent()

        assert result["notifications_created"] == 0

    @patch("apps.notifications.tasks.create_notification.delay")
    def test_no_duplicate_imminent(self, mock_delay, opportunity_with_dates):
        """Running imminent check twice does not duplicate alerts."""
        opportunity_with_dates.proposals_open_at = timezone.now() + timedelta(minutes=10)
        opportunity_with_dates.save(update_fields=["proposals_open_at"])

        result1 = check_session_imminent()
        result2 = check_session_imminent()

        assert result1["notifications_created"] > 0
        assert result2["notifications_created"] == 0

        # Only one internal imminent notification
        count = EventNotification.objects.filter(
            event_type=EventNotification.EventType.SESSION_IMMINENT,
            opportunity_id=opportunity_with_dates.pk,
        ).count()
        assert count == 1
