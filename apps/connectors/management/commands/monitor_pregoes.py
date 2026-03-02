"""Management command — monitoramento de pregões sob demanda."""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Monitor PNCP procurements for changes (status, docs, results, atas)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours-back",
            type=int,
            default=6,
            help="Hours to look back for updates (default: 6)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously instead of dispatching as Celery task",
        )

    def handle(self, *args, **options):
        hours_back = options["hours_back"]
        sync = options["sync"]

        if sync:
            self.stdout.write(f"Running monitor_pregoes synchronously (hours_back={hours_back})...")
            from apps.connectors.tasks import monitor_pregoes
            result = monitor_pregoes(hours_back=hours_back)
            self.stdout.write(self.style.SUCCESS(f"Done: {result}"))
        else:
            self.stdout.write(f"Dispatching monitor_pregoes task (hours_back={hours_back})...")
            from apps.connectors.tasks import monitor_pregoes
            monitor_pregoes.delay(hours_back=hours_back)
            self.stdout.write(self.style.SUCCESS("Task dispatched to Celery"))
