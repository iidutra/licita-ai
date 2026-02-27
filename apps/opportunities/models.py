"""Opportunity domain models — Edital, Itens, Documentos, IA, Matching."""
from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import VectorField

from apps.core.models import TimeStampedModel
from apps.core.storage import document_upload_path


class Opportunity(TimeStampedModel):
    """Licitação/oportunidade capturada das fontes oficiais."""

    class Source(models.TextChoices):
        PNCP = "pncp", "PNCP"
        COMPRAS_GOV = "compras_gov", "Compras.gov.br"
        MANUAL = "manual", "Cadastro Manual"

    class Status(models.TextChoices):
        NEW = "new", "Novo"
        ANALYZING = "analyzing", "Em Análise"
        ELIGIBLE = "eligible", "Apto"
        DISCARDED = "discarded", "Descartado"
        SUBMITTED = "submitted", "Proposta Enviada"

    class Modality(models.TextChoices):
        PREGAO_ELETRONICO = "pregao_eletronico", "Pregão Eletrônico"
        PREGAO_PRESENCIAL = "pregao_presencial", "Pregão Presencial"
        CONCORRENCIA_ELETRONICA = "concorrencia_eletronica", "Concorrência Eletrônica"
        CONCORRENCIA_PRESENCIAL = "concorrencia_presencial", "Concorrência Presencial"
        DISPENSA = "dispensa", "Dispensa de Licitação"
        INEXIGIBILIDADE = "inexigibilidade", "Inexigibilidade"
        CONCURSO = "concurso", "Concurso"
        LEILAO = "leilao", "Leilão"
        DIALOGO_COMPETITIVO = "dialogo_competitivo", "Diálogo Competitivo"
        CREDENCIAMENTO = "credenciamento", "Credenciamento"
        OTHER = "other", "Outra"

    # Identificação
    source = models.CharField("Fonte", max_length=20, choices=Source.choices, db_index=True)
    external_id = models.CharField(
        "ID externo", max_length=200, help_text="ID original na fonte"
    )
    dedup_hash = models.CharField(
        "Hash de dedup", max_length=64, unique=True,
        help_text="SHA-256 de source:external_id para idempotência"
    )
    object_hash = models.CharField(
        "Hash do objeto", max_length=64, db_index=True,
        help_text="SHA-256 do objeto normalizado para dedup cross-source"
    )

    # Dados do edital
    title = models.TextField("Objeto da contratação")
    description = models.TextField("Informação complementar", blank=True, default="")
    modality = models.CharField(
        "Modalidade", max_length=30, choices=Modality.choices, default=Modality.OTHER
    )
    number = models.CharField("Número da compra", max_length=100, blank=True)
    process_number = models.CharField("Nº do processo", max_length=100, blank=True)

    # Órgão
    entity_cnpj = models.CharField("CNPJ do órgão", max_length=18, db_index=True)
    entity_name = models.CharField("Nome do órgão", max_length=400)
    entity_uf = models.CharField("UF", max_length=2, db_index=True, blank=True)
    entity_city = models.CharField("Município", max_length=200, blank=True)

    # Datas
    published_at = models.DateTimeField("Publicação", null=True, blank=True, db_index=True)
    proposals_open_at = models.DateTimeField("Abertura de propostas", null=True, blank=True)
    proposals_close_at = models.DateTimeField("Encerramento de propostas", null=True, blank=True)
    deadline = models.DateTimeField(
        "Prazo final", null=True, blank=True, db_index=True,
        help_text="Data-limite para participação/entrega"
    )

    # Valores
    estimated_value = models.DecimalField(
        "Valor estimado", max_digits=15, decimal_places=2, null=True, blank=True
    )
    awarded_value = models.DecimalField(
        "Valor homologado", max_digits=15, decimal_places=2, null=True, blank=True
    )
    is_srp = models.BooleanField("SRP (Registro de preço)", default=False)

    # Metadados extras da API (guardamos o JSON bruto)
    raw_data = models.JSONField("Dados brutos da API", default=dict, blank=True)
    link = models.URLField("Link no sistema de origem", max_length=2000, blank=True)

    # Status interno
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.NEW, db_index=True
    )

    class Meta:
        verbose_name = "Oportunidade"
        verbose_name_plural = "Oportunidades"
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["source", "external_id"], name="idx_source_extid"),
            models.Index(fields=["entity_uf", "status"], name="idx_uf_status"),
            models.Index(fields=["deadline", "status"], name="idx_deadline_status"),
        ]

    def __str__(self):
        return f"[{self.get_source_display()}] {self.title[:80]}"


class OpportunityItem(TimeStampedModel):
    """Item individual de uma licitação."""

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="items"
    )
    item_number = models.PositiveIntegerField("Nº do item")
    description = models.TextField("Descrição")
    quantity = models.DecimalField(
        "Quantidade", max_digits=15, decimal_places=4, null=True, blank=True
    )
    unit = models.CharField("Unidade", max_length=50, blank=True)
    estimated_unit_price = models.DecimalField(
        "Preço unitário estimado", max_digits=15, decimal_places=4, null=True, blank=True
    )
    estimated_total = models.DecimalField(
        "Valor total estimado", max_digits=15, decimal_places=2, null=True, blank=True
    )
    material_or_service = models.CharField(
        "Material/Serviço", max_length=20, blank=True
    )
    raw_data = models.JSONField("Dados brutos", default=dict, blank=True)

    class Meta:
        verbose_name = "Item da Oportunidade"
        verbose_name_plural = "Itens da Oportunidade"
        ordering = ["item_number"]
        unique_together = [("opportunity", "item_number")]

    def __str__(self):
        return f"Item {self.item_number}: {self.description[:60]}"


class OpportunityDocument(TimeStampedModel):
    """Anexo/documento de uma licitação (edital, TR, planilha, etc.)."""

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        DOWNLOADING = "downloading", "Baixando"
        DOWNLOADED = "downloaded", "Baixado"
        EXTRACTING = "extracting", "Extraindo texto"
        INDEXED = "indexed", "Indexado"
        FAILED = "failed", "Falhou"

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="documents"
    )
    original_url = models.URLField("URL original")
    file = models.FileField("Arquivo local", upload_to=document_upload_path, blank=True)
    file_hash = models.CharField("SHA-256", max_length=64, blank=True, db_index=True)
    file_name = models.CharField("Nome do arquivo", max_length=500, blank=True)
    file_size = models.PositiveIntegerField("Tamanho (bytes)", null=True, blank=True)
    mime_type = models.CharField("MIME type", max_length=100, blank=True)
    doc_type = models.CharField("Tipo", max_length=100, blank=True)

    # Processing
    processing_status = models.CharField(
        "Status", max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    extracted_text = models.TextField("Texto extraído", blank=True)
    page_count = models.PositiveIntegerField("Páginas", null=True, blank=True)
    ocr_used = models.BooleanField("OCR utilizado", default=False)
    error_message = models.TextField("Erro", blank=True)

    class Meta:
        verbose_name = "Documento da Oportunidade"
        verbose_name_plural = "Documentos da Oportunidade"

    def __str__(self):
        return f"{self.file_name or self.original_url[:60]}"


class DocumentChunk(TimeStampedModel):
    """Chunk de texto de um documento para RAG com embedding vetorial."""

    document = models.ForeignKey(
        OpportunityDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    chunk_index = models.PositiveIntegerField("Índice do chunk")
    content = models.TextField("Conteúdo do chunk")
    page_number = models.PositiveIntegerField("Página", null=True, blank=True)
    token_count = models.PositiveIntegerField("Tokens", null=True, blank=True)
    embedding = VectorField(
        "Embedding", dimensions=3072, null=True, blank=True
    )

    class Meta:
        verbose_name = "Chunk de Documento"
        verbose_name_plural = "Chunks de Documentos"
        ordering = ["chunk_index"]
        unique_together = [("document", "chunk_index")]
        indexes = [
            models.Index(fields=["document", "chunk_index"], name="idx_chunk_doc_idx"),
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} — {self.document.file_name}"


class ExtractedRequirement(TimeStampedModel):
    """Requisito extraído por IA de um edital, com evidência."""

    class Category(models.TextChoices):
        FISCAL = "fiscal", "Habilitação Fiscal"
        JURIDICA = "juridica", "Habilitação Jurídica"
        TECNICA = "tecnica", "Qualificação Técnica"
        ECONOMICA = "economica", "Qualificação Econômico-Financeira"
        GENERAL = "general", "Requisito Geral"

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="requirements"
    )
    category = models.CharField(
        "Categoria", max_length=20, choices=Category.choices
    )
    requirement = models.TextField("Requisito")
    evidence = models.JSONField(
        "Evidência",
        default=dict,
        help_text='{"source": "api|document", "excerpt": "...", "page": 3, "confidence": 0.95}',
    )
    is_mandatory = models.BooleanField("Obrigatório", default=True)

    class Meta:
        verbose_name = "Requisito Extraído"
        verbose_name_plural = "Requisitos Extraídos"

    def __str__(self):
        return f"[{self.get_category_display()}] {self.requirement[:80]}"


class AISummary(TimeStampedModel):
    """Resultado da análise de IA sobre uma oportunidade."""

    class AnalysisType(models.TextChoices):
        EXECUTIVE_SUMMARY = "summary", "Resumo Executivo"
        CHECKLIST = "checklist", "Checklist de Habilitação"
        RISKS = "risks", "Riscos e Pegadinhas"
        FULL = "full", "Análise Completa"

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="ai_summaries"
    )
    analysis_type = models.CharField(
        "Tipo", max_length=20, choices=AnalysisType.choices
    )
    content = models.JSONField(
        "Conteúdo",
        help_text="JSON com resumo, checklist, riscos — conforme analysis_type",
    )
    prompt_version = models.CharField("Versão do prompt", max_length=50)
    model_name = models.CharField("Modelo IA", max_length=100)
    tokens_used = models.PositiveIntegerField("Tokens consumidos", default=0)
    processing_time_ms = models.PositiveIntegerField("Tempo (ms)", default=0)

    class Meta:
        verbose_name = "Resumo IA"
        verbose_name_plural = "Resumos IA"

    def __str__(self):
        return f"{self.get_analysis_type_display()} — {self.opportunity}"
