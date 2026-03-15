"""One-shot command to fix stuck documents in the pipeline.

Handles:
1. downloaded docs without file (dedup bug) → reset to pending for re-download
2. failed docs with NUL byte error → reset to downloaded for re-extraction
3. downloading docs stuck for > 1 hour → reset to pending
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.opportunities.models import OpportunityDocument
from apps.opportunities.tasks import download_single_document, extract_document_text


class Command(BaseCommand):
    help = "Fix stuck documents and re-enqueue them for processing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Only show what would be done, without making changes",
        )
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Max documents to re-enqueue per category (default: 500)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # 1. Downloaded without file → re-download
        no_file = OpportunityDocument.objects.filter(
            processing_status=OpportunityDocument.ProcessingStatus.DOWNLOADED,
            original_url__gt="",
        ).filter(file="")[:batch_size]
        count_no_file = no_file.count()
        self.stdout.write(f"Downloaded without file: {count_no_file}")

        if not dry_run:
            for doc in no_file:
                doc.processing_status = OpportunityDocument.ProcessingStatus.PENDING
                doc.error_message = ""
                doc.save(update_fields=["processing_status", "error_message", "updated_at"])
                download_single_document.delay(str(doc.pk))
            self.stdout.write(self.style.SUCCESS(f"  Re-queued {count_no_file} for download"))

        # 2. Downloaded WITH file but never extracted → enqueue extraction
        has_file_not_extracted = OpportunityDocument.objects.filter(
            processing_status=OpportunityDocument.ProcessingStatus.DOWNLOADED,
        ).exclude(file="")[:batch_size]
        count_has_file = has_file_not_extracted.count()
        self.stdout.write(f"Downloaded with file, not extracted: {count_has_file}")

        if not dry_run:
            for doc in has_file_not_extracted:
                extract_document_text.delay(str(doc.pk))
            self.stdout.write(self.style.SUCCESS(f"  Re-queued {count_has_file} for extraction"))

        # 3. Failed with NUL error → reset to downloaded for re-extraction
        nul_failed = OpportunityDocument.objects.filter(
            processing_status=OpportunityDocument.ProcessingStatus.FAILED,
            error_message__icontains="NUL",
        ).exclude(file="")[:batch_size]
        count_nul = nul_failed.count()
        self.stdout.write(f"Failed with NUL error (has file): {count_nul}")

        if not dry_run:
            for doc in nul_failed:
                doc.processing_status = OpportunityDocument.ProcessingStatus.DOWNLOADED
                doc.error_message = ""
                doc.save(update_fields=["processing_status", "error_message", "updated_at"])
                extract_document_text.delay(str(doc.pk))
            self.stdout.write(self.style.SUCCESS(f"  Re-queued {count_nul} for extraction"))

        # 4. Stuck in downloading for > 1 hour → reset to pending
        one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
        stuck_downloading = OpportunityDocument.objects.filter(
            processing_status=OpportunityDocument.ProcessingStatus.DOWNLOADING,
            updated_at__lt=one_hour_ago,
            original_url__gt="",
        )[:batch_size]
        count_stuck = stuck_downloading.count()
        self.stdout.write(f"Stuck in downloading > 1h: {count_stuck}")

        if not dry_run:
            for doc in stuck_downloading:
                doc.processing_status = OpportunityDocument.ProcessingStatus.PENDING
                doc.error_message = ""
                doc.save(update_fields=["processing_status", "error_message", "updated_at"])
                download_single_document.delay(str(doc.pk))
            self.stdout.write(self.style.SUCCESS(f"  Re-queued {count_stuck} for download"))

        # 5. Opportunities stuck in 'analyzing' with no AI summaries → revert to 'new'
        from apps.opportunities.models import Opportunity
        stuck_analyzing = Opportunity.objects.filter(
            status=Opportunity.Status.ANALYZING,
        ).exclude(ai_summaries__isnull=False)
        count_analyzing = stuck_analyzing.count()
        self.stdout.write(f"Opportunities stuck in 'analyzing': {count_analyzing}")

        if not dry_run:
            stuck_analyzing.update(status=Opportunity.Status.NEW)
            self.stdout.write(self.style.SUCCESS(f"  Reverted {count_analyzing} to 'new'"))

        # Summary
        total = count_no_file + count_has_file + count_nul + count_stuck
        if dry_run:
            self.stdout.write(self.style.WARNING(f"\nDRY RUN: {total} docs would be re-queued, {count_analyzing} opps would be reverted"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nTotal re-queued: {total}, Opps reverted: {count_analyzing}"))
