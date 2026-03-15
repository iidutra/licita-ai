"""Fix Compras.gov document URLs: replace portal links with real PNCP API file URLs."""
import logging
import re
import time

import httpx
from django.core.management.base import BaseCommand

from apps.opportunities.models import Opportunity, OpportunityDocument

logger = logging.getLogger(__name__)

PORTAL_PATTERN = re.compile(
    r"https://pncp\.gov\.br/app/editais/(\d{14})/(\d{4})/(\d+)"
)


class Command(BaseCommand):
    help = "Fix Compras.gov documents that have portal URLs instead of API file URLs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be fixed without making changes",
        )
        parser.add_argument(
            "--batch-size", type=int, default=100,
            help="Number of documents to process per batch",
        )
        parser.add_argument(
            "--opportunity-id", type=str, default=None,
            help="Fix only documents for a specific opportunity",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        opp_id = options["opportunity_id"]

        qs = OpportunityDocument.objects.filter(
            opportunity__source=Opportunity.Source.COMPRAS_GOV,
            original_url__contains="/app/editais/",
        )
        if opp_id:
            qs = qs.filter(opportunity_id=opp_id)

        total = qs.count()
        self.stdout.write(f"Found {total} documents with portal URLs to fix")

        if dry_run:
            for doc in qs[:10]:
                self.stdout.write(f"  {doc.id}: {doc.original_url}")
            return

        client = httpx.Client(timeout=30, follow_redirects=True, headers={
            "Accept": "application/json", "User-Agent": "LicitaAI/1.0",
        })

        fixed = 0
        errors = 0
        processed_opps = set()

        for doc in qs.select_related("opportunity").iterator(chunk_size=batch_size):
            opp = doc.opportunity
            match = PORTAL_PATTERN.match(doc.original_url)
            if not match:
                continue

            cnpj, ano, seq = match.groups()
            opp_key = f"{cnpj}/{ano}/{seq}"

            # Fetch real docs from PNCP API (once per opportunity)
            if opp_key not in processed_opps:
                try:
                    resp = client.get(
                        f"https://pncp.gov.br/pncp-api/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos"
                    )
                    resp.raise_for_status()
                    api_docs = resp.json()
                    if not isinstance(api_docs, list):
                        api_docs = api_docs.get("data", [])
                except Exception as e:
                    self.stderr.write(f"  API error for {opp_key}: {e}")
                    errors += 1
                    time.sleep(1)
                    continue

                processed_opps.add(opp_key)

                # Delete the old portal-URL document
                doc.delete()

                # Create real document records
                existing_urls = set(
                    opp.documents.values_list("original_url", flat=True)
                )
                for api_doc in api_docs:
                    url = api_doc.get("uri") or api_doc.get("url", "")
                    if url and url not in existing_urls:
                        OpportunityDocument.objects.create(
                            opportunity=opp,
                            original_url=url,
                            file_name=api_doc.get("nomeArquivo", ""),
                            doc_type=api_doc.get("tipoDocumentoNome", ""),
                            processing_status=OpportunityDocument.ProcessingStatus.PENDING,
                        )
                        fixed += 1

                # Rate limiting
                time.sleep(0.5)

            else:
                # Already processed this opportunity, just delete duplicate portal doc
                doc.delete()

            if (fixed + errors) % 100 == 0 and fixed > 0:
                self.stdout.write(f"  Progress: {fixed} fixed, {errors} errors")

        client.close()
        self.stdout.write(self.style.SUCCESS(
            f"Done: {fixed} documents fixed, {errors} errors, "
            f"{len(processed_opps)} opportunities processed"
        ))
