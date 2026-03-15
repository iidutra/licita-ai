"""Celery configuration for LicitaAI."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("licitaai")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ── Named queues ────────────────────────────────────────
app.conf.task_routes = {
    "apps.connectors.tasks.*": {"queue": "ingest"},
    "apps.ai_engine.tasks.*": {"queue": "ai"},
    "apps.opportunities.tasks.download_*": {"queue": "documents"},
    "apps.notifications.tasks.*": {"queue": "notifications"},
}

# ── Beat schedule (periodic tasks) ─────────────────────
app.conf.beat_schedule = {
    # Coleta diária PNCP — 06:00 UTC (03:00 BRT)
    # days_back=3 para cobrir fins de semana e feriados
    "ingest-pncp-daily": {
        "task": "apps.connectors.tasks.ingest_pncp",
        "schedule": crontab(hour=6, minute=0),
        "kwargs": {"days_back": 3},
        "options": {"queue": "ingest"},
    },
    # Coleta diária Compras.gov — 06:30 UTC
    "ingest-compras-gov-daily": {
        "task": "apps.connectors.tasks.ingest_compras_gov",
        "schedule": crontab(hour=6, minute=30),
        "kwargs": {"days_back": 3},
        "options": {"queue": "ingest"},
    },
    # Avisos de prazo (escala progressiva) — 2x/dia: 08:00 e 14:00 UTC (05:00 e 11:00 BRT)
    "check-deadlines": {
        "task": "apps.notifications.tasks.check_critical_deadlines",
        "schedule": crontab(hour="8,14", minute=0),
        "options": {"queue": "notifications"},
    },
    # Avisos de abertura/sessão — 2x/dia: 08:15 e 18:15 UTC (05:15 e 15:15 BRT)
    "check-proposals-opening": {
        "task": "apps.notifications.tasks.check_proposals_opening",
        "schedule": crontab(hour="8,18", minute=15),
        "options": {"queue": "notifications"},
    },
    # Alerta de sessão iminente — a cada 5 min (07:00–23:00 UTC = 04:00–20:00 BRT)
    "check-session-imminent": {
        "task": "apps.notifications.tasks.check_session_imminent",
        "schedule": crontab(minute="*/5", hour="7-23"),
        "options": {"queue": "notifications"},
    },
    # Monitoramento de pregões — 5x/dia em horário comercial BRT (UTC-3)
    # 08:30, 11:30, 14:30, 17:30, 20:30 BRT = 11:30, 14:30, 17:30, 20:30, 23:30 UTC
    "monitor-pregoes": {
        "task": "apps.connectors.tasks.monitor_pregoes",
        "schedule": crontab(minute=30, hour="11,14,17,20,23"),
        "kwargs": {"hours_back": 6},
        "options": {"queue": "ingest"},
    },
}
