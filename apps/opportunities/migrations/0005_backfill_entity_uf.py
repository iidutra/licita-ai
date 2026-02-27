"""Backfill entity_uf and entity_city from raw_data for existing records."""
from django.db import migrations


def backfill_uf(apps, schema_editor):
    Opportunity = apps.get_model("opportunities", "Opportunity")
    updated = 0
    for opp in Opportunity.objects.filter(entity_uf=""):
        raw = opp.raw_data or {}
        unidade = raw.get("unidadeOrgao", {})
        uf = unidade.get("ufSigla", "")
        city = unidade.get("municipioNome", "")
        if uf:
            opp.entity_uf = uf
            if city and not opp.entity_city:
                opp.entity_city = city
            opp.save(update_fields=["entity_uf", "entity_city"])
            updated += 1
    if updated:
        print(f"\n  Backfilled entity_uf for {updated} opportunities")


class Migration(migrations.Migration):
    dependencies = [
        ("opportunities", "0004_change_embedding_3072"),
    ]

    operations = [
        migrations.RunPython(backfill_uf, migrations.RunPython.noop),
    ]
