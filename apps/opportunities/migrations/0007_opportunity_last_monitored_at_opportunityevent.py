# Generated manually for pregão monitoring feature

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('opportunities', '0006_increase_link_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='opportunity',
            name='last_monitored_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Última verificação'),
        ),
        migrations.CreateModel(
            name='OpportunityEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event_type', models.CharField(
                    choices=[
                        ('status_change', 'Mudança de Status'),
                        ('new_document', 'Novo Documento'),
                        ('result_published', 'Resultado Publicado'),
                        ('ata_published', 'Ata Publicada'),
                        ('deadline_changed', 'Prazo Alterado'),
                        ('value_changed', 'Valor Alterado'),
                        ('general_update', 'Atualização Geral'),
                    ],
                    db_index=True,
                    max_length=30,
                    verbose_name='Tipo do evento',
                )),
                ('old_value', models.TextField(blank=True, default='', verbose_name='Valor anterior')),
                ('new_value', models.TextField(blank=True, default='', verbose_name='Valor novo')),
                ('description', models.TextField(blank=True, default='', verbose_name='Descrição')),
                ('raw_data', models.JSONField(blank=True, default=dict, verbose_name='Dados brutos')),
                ('dedup_hash', models.CharField(
                    help_text='SHA-256 para idempotência do evento',
                    max_length=64,
                    unique=True,
                    verbose_name='Hash de dedup',
                )),
                ('detected_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Detectado em')),
                ('opportunity', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='events',
                    to='opportunities.opportunity',
                )),
            ],
            options={
                'verbose_name': 'Evento da Oportunidade',
                'verbose_name_plural': 'Eventos das Oportunidades',
                'ordering': ['-detected_at'],
            },
        ),
    ]
