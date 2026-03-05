"""Backfill opportunity fields from raw_data."""
from django.core.management.base import BaseCommand

from apps.opportunities.models import Opportunity


class Command(BaseCommand):
    help = "Backfill process_number and other fields from raw_data"

    def handle(self, *args, **options):
        updated = 0
        qs = Opportunity.objects.exclude(raw_data={})

        for opp in qs.iterator(chunk_size=500):
            changed = False
            raw = opp.raw_data

            # process_number
            process = (
                raw.get("processo")
                or raw.get("numeroProcesso")
                or raw.get("process_number")
                or ""
            )
            if process and not opp.process_number:
                opp.process_number = str(process)[:100]
                changed = True

            # number
            number = raw.get("numeroCompra") or raw.get("numero") or ""
            if number and not opp.number:
                opp.number = str(number)[:100]
                changed = True

            # entity_uf
            unidade = raw.get("unidadeOrgao", {})
            if isinstance(unidade, dict):
                uf = unidade.get("ufSigla", "")
            else:
                uf = raw.get("unidadeOrgaoUfSigla", "")
            if uf and not opp.entity_uf:
                opp.entity_uf = str(uf)[:2]
                changed = True

            # entity_city
            if isinstance(unidade, dict):
                city = unidade.get("municipioNome", "")
            else:
                city = raw.get("unidadeOrgaoMunicipioNome", "")
            if city and not opp.entity_city:
                opp.entity_city = str(city)[:200]
                changed = True

            # link (build PNCP portal link if missing)
            if not opp.link:
                link = raw.get("linkSistemaOrigem", "")
                if not link:
                    orgao = raw.get("orgaoEntidade", {})
                    cnpj = orgao.get("cnpj", "") if isinstance(orgao, dict) else ""
                    ano = raw.get("anoCompra", "")
                    seq = raw.get("sequencialCompra", "")
                    if cnpj and ano and seq:
                        link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
                if link:
                    opp.link = link[:500]
                    changed = True

            if changed:
                opp.save(update_fields=[
                    "process_number", "number", "entity_uf", "entity_city", "link",
                ])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} opportunities"))
