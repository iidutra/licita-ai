"""Event notifications and audit trail."""
from django.db import models

from apps.core.models import TimeStampedModel


class EventNotification(TimeStampedModel):
    """Registro de notificação/evento do sistema."""

    class EventType(models.TextChoices):
        NEW_OPPORTUNITY = "new_opportunity", "Nova Oportunidade"
        HIGH_SCORE_MATCH = "high_score_match", "Match com score alto"
        DEADLINE_WARNING = "deadline_warning", "Prazo crítico"
        AI_COMPLETE = "ai_complete", "Análise IA concluída"
        DOCUMENT_READY = "document_ready", "Documento processado"
        INGESTION_ERROR = "ingestion_error", "Erro de ingestão"

    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        WEBHOOK = "webhook", "Webhook"
        INTERNAL = "internal", "Interno (dashboard)"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        SENT = "sent", "Enviado"
        FAILED = "failed", "Falhou"

    event_type = models.CharField(
        "Tipo", max_length=30, choices=EventType.choices, db_index=True
    )
    channel = models.CharField(
        "Canal", max_length=20, choices=Channel.choices, default=Channel.INTERNAL
    )
    recipient = models.CharField("Destinatário", max_length=300, blank=True)
    subject = models.CharField("Assunto", max_length=300)
    body = models.TextField("Corpo")
    payload = models.JSONField("Payload extra", default=dict, blank=True)
    delivery_status = models.CharField(
        "Status de entrega", max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    sent_at = models.DateTimeField("Enviado em", null=True, blank=True)
    error_message = models.TextField("Erro", blank=True)

    # Referências opcionais
    opportunity_id = models.UUIDField("Oportunidade", null=True, blank=True)
    client_id = models.UUIDField("Cliente", null=True, blank=True)

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_event_type_display()}] {self.subject}"
