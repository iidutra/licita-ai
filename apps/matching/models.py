"""Matching: score de aderência cliente x edital."""
from django.db import models

from apps.clients.models import Client
from apps.core.models import TimeStampedModel
from apps.opportunities.models import Opportunity


class Match(TimeStampedModel):
    """Resultado do matching entre cliente e oportunidade."""

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="matches"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="matches"
    )
    score = models.PositiveSmallIntegerField(
        "Score (0-100)", help_text="0 = sem aderência, 100 = perfeito"
    )
    justification = models.TextField("Justificativa do score")
    missing_docs = models.JSONField(
        "Documentos faltantes",
        default=list,
        help_text='[{"type": "atestado_tecnico", "reason": "..."}]',
    )
    missing_capabilities = models.JSONField(
        "Competências faltantes", default=list
    )
    evidence = models.JSONField(
        "Evidências",
        default=list,
        help_text="Lista de evidências usadas no matching",
    )
    prompt_version = models.CharField("Versão do prompt", max_length=50)
    model_name = models.CharField("Modelo IA", max_length=100)

    class Meta:
        verbose_name = "Match"
        verbose_name_plural = "Matches"
        unique_together = [("opportunity", "client")]
        ordering = ["-score"]

    def __str__(self):
        return f"{self.client.name} ↔ {self.opportunity.title[:50]} ({self.score}/100)"
