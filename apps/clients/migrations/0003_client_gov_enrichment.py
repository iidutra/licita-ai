"""Add government enrichment fields to Client."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0002_add_whatsapp_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="gov_supplier_active",
            field=models.BooleanField(
                blank=True, null=True, verbose_name="Fornecedor ativo (gov)"
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="gov_porte",
            field=models.CharField(
                blank=True, max_length=50, verbose_name="Porte da empresa"
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="gov_ramo_negocio",
            field=models.CharField(
                blank=True, max_length=300, verbose_name="Ramo de negócio"
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="gov_natureza_juridica",
            field=models.CharField(
                blank=True, max_length=200, verbose_name="Natureza jurídica"
            ),
        ),
    ]
