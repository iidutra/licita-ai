"""Management command — ingestão PNCP sob demanda."""
import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.connectors.normalizer import persist_opportunity
from apps.connectors.pncp import PNCPConnector, ALL_MODALITIES, DEFAULT_MODALITIES, MODALITY_MAP

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ingest opportunities from PNCP for a given period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-back",
            type=int,
            default=30,
            help="Number of days to look back (default: 30)",
        )
        parser.add_argument(
            "--uf",
            type=str,
            default=None,
            help="Filter by UF (e.g. SP, RJ, PR)",
        )
        parser.add_argument(
            "--keyword",
            type=str,
            default=None,
            help="Filter by keyword in title/description (post-fetch)",
        )
        parser.add_argument(
            "--all-modalities",
            action="store_true",
            help="Fetch ALL 13 modalities instead of just the 6 most relevant",
        )
        parser.add_argument(
            "--modalities",
            type=str,
            default=None,
            help="Comma-separated modality IDs to fetch (e.g. 6,4,8)",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=0,
            help="Max pages per modality (0 = unlimited). Use to limit during testing.",
        )
        parser.add_argument(
            "--skip-items",
            action="store_true",
            help="Skip fetching items per opportunity (faster)",
        )
        parser.add_argument(
            "--skip-docs",
            action="store_true",
            help="Skip fetching documents per opportunity (faster)",
        )
        parser.add_argument(
            "--window",
            type=int,
            default=0,
            help="Split date range into windows of N days (0 = no split). "
                 "Useful for large backfills to avoid memory issues.",
        )

    def handle(self, *args, **options):
        days_back = options["days_back"]
        uf = options["uf"]
        keyword = options["keyword"]
        skip_items = options["skip_items"]
        skip_docs = options["skip_docs"]
        max_pages = options["max_pages"]
        window = options["window"]

        # Resolve modalities
        if options["modalities"]:
            modalities = [int(m.strip()) for m in options["modalities"].split(",")]
        elif options["all_modalities"]:
            modalities = ALL_MODALITIES
        else:
            modalities = DEFAULT_MODALITIES

        mod_names = ", ".join(f"{m}={MODALITY_MAP.get(m, '?')}" for m in modalities)
        self.stdout.write(f"Modalities: {mod_names}")

        date_to = date.today()
        date_from = date_to - timedelta(days=days_back)

        # Split into windows if requested
        if window > 0:
            windows = []
            w_start = date_from
            while w_start < date_to:
                w_end = min(w_start + timedelta(days=window), date_to)
                windows.append((w_start, w_end))
                w_start = w_end + timedelta(days=1)
        else:
            windows = [(date_from, date_to)]

        total_created = 0
        total_existing = 0
        total_fetched = 0

        with PNCPConnector() as connector:
            for w_idx, (w_from, w_to) in enumerate(windows, 1):
                self.stdout.write(
                    f"\n{'='*60}\n"
                    f"Window {w_idx}/{len(windows)}: {w_from} to {w_to} "
                    f"(uf={uf}, keyword={keyword})\n"
                    f"{'='*60}"
                )

                opportunities = connector.fetch_opportunities(
                    date_from=w_from,
                    date_to=w_to,
                    uf=uf,
                    keyword=keyword,
                    modalities=modalities,
                    max_pages=max_pages,
                    on_progress=lambda msg: self.stdout.write(msg),
                )
                total_fetched += len(opportunities)
                self.stdout.write(f"Fetched {len(opportunities)} opportunities from API")

                created_count = 0
                error_count = 0
                for i, norm_opp in enumerate(opportunities, 1):
                    if not skip_items:
                        try:
                            norm_opp.items = connector.fetch_items(norm_opp)
                        except Exception:
                            pass

                    if not skip_docs:
                        try:
                            norm_opp.document_urls = connector.fetch_documents(norm_opp)
                        except Exception:
                            pass

                    try:
                        opp, created = persist_opportunity(norm_opp)
                        if created:
                            created_count += 1
                    except Exception as e:
                        error_count += 1
                        if error_count <= 5:
                            self.stderr.write(f"  ERROR persisting {norm_opp.external_id}: {e}")

                    if i % 100 == 0:
                        self.stdout.write(f"  ... persisted {i}/{len(opportunities)}")

                total_created += created_count
                total_existing += len(opportunities) - created_count
                self.stdout.write(
                    f"Window result: {created_count} new, "
                    f"{len(opportunities) - created_count} existing"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {total_created} new, {total_existing} existing, "
                f"{total_fetched} total fetched"
            )
        )
