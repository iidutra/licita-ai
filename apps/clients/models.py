"""Client domain models."""
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import TimeStampedModel


class Client(TimeStampedModel):
    """Empresa/cliente que busca oportunidades de licitação."""

    name = models.CharField("Razão Social", max_length=300)
    cnpj = models.CharField("CNPJ", max_length=18, unique=True)
    trade_name = models.CharField("Nome Fantasia", max_length=300, blank=True)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefone", max_length=20, blank=True)

    # Perfil de matching
    regions = ArrayField(
        models.CharField(max_length=2),
        verbose_name="UFs de interesse",
        help_text="Lista de UFs (ex: SP, RJ, MG)",
        default=list,
        blank=True,
    )
    keywords = ArrayField(
        models.CharField(max_length=100),
        verbose_name="Palavras-chave",
        help_text="Palavras-chave do catálogo/serviços",
        default=list,
        blank=True,
    )
    categories = ArrayField(
        models.CharField(max_length=100),
        verbose_name="Categorias de serviço/produto",
        default=list,
        blank=True,
    )
    min_margin_pct = models.DecimalField(
        "Margem mínima (%)", max_digits=5, decimal_places=2, default=0
    )
    max_value = models.DecimalField(
        "Valor máximo de contrato", max_digits=15, decimal_places=2, null=True, blank=True
    )
    logistics_reach = ArrayField(
        models.CharField(max_length=2),
        verbose_name="Alcance logístico (UFs)",
        default=list,
        blank=True,
    )
    restrictions = models.TextField("Restrições", blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    notify_email = models.BooleanField("Notificar por e-mail", default=True)
    webhook_url = models.URLField("Webhook URL", blank=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.cnpj})"


class ClientDocument(TimeStampedModel):
    """Documento/certificado do cliente (CND, atestado, certidão, etc.)."""

    class DocType(models.TextChoices):
        CND_FEDERAL = "cnd_federal", "CND Federal"
        CND_ESTADUAL = "cnd_estadual", "CND Estadual"
        CND_MUNICIPAL = "cnd_municipal", "CND Municipal"
        FGTS = "fgts", "CRF/FGTS"
        CNDT = "cndt", "CNDT (Trabalhista)"
        BALANCO = "balanco", "Balanço Patrimonial"
        ATESTADO_TECNICO = "atestado_tecnico", "Atestado Técnico"
        CONTRATO_SOCIAL = "contrato_social", "Contrato Social"
        PROCURACAO = "procuracao", "Procuração"
        SICAF = "sicaf", "SICAF"
        OTHER = "other", "Outro"

    class DocStatus(models.TextChoices):
        VALID = "valid", "Válido"
        EXPIRING = "expiring", "A vencer (< 30 dias)"
        EXPIRED = "expired", "Vencido"
        PENDING = "pending", "Pendente"

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField("Tipo", max_length=30, choices=DocType.choices)
    description = models.CharField("Descrição", max_length=300, blank=True)
    file = models.FileField("Arquivo", upload_to="client_docs/%Y/%m/", blank=True)
    url = models.URLField("URL externa", blank=True)
    issued_at = models.DateField("Data de emissão", null=True, blank=True)
    expires_at = models.DateField("Data de validade", null=True, blank=True)
    status = models.CharField(
        "Status", max_length=20, choices=DocStatus.choices, default=DocStatus.PENDING
    )

    class Meta:
        verbose_name = "Documento do Cliente"
        verbose_name_plural = "Documentos do Cliente"

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.client.name}"
