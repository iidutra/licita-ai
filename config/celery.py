"""Celery configuration for LicitaAI."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

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
    # Download pendente de anexos — a cada 2 horas
    "download-pending-documents": {
        "task": "apps.opportunities.tasks.download_pending_documents",
        "schedule": crontab(minute=0, hour="*/2"),
        "options": {"queue": "documents"},
    },
    # Checar prazos críticos — diariamente 08:00 UTC
    "check-deadlines": {
        "task": "apps.notifications.tasks.check_critical_deadlines",
        "schedule": crontab(hour=8, minute=0),
        "options": {"queue": "notifications"},
    },
}
