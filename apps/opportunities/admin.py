from django.contrib import admin

from .models import (
    AISummary,
    DocumentChunk,
    ExtractedRequirement,
    Opportunity,
    OpportunityDocument,
    OpportunityItem,
)


class OpportunityItemInline(admin.TabularInline):
    model = OpportunityItem
    extra = 0
    fields = ["item_number", "description", "quantity", "unit", "estimated_unit_price"]


class OpportunityDocumentInline(admin.TabularInline):
    model = OpportunityDocument
    extra = 0
    fields = ["file_name", "doc_type", "processing_status", "original_url"]
    readonly_fields = ["file_hash"]


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = [
        "title_short", "source", "entity_uf", "modality",
        "estimated_value", "status", "published_at",
    ]
    list_filter = ["source", "status", "modality", "entity_uf"]
    search_fields = ["title", "entity_name", "entity_cnpj", "number"]
    readonly_fields = ["dedup_hash", "object_hash", "raw_data"]
    inlines = [OpportunityItemInline, OpportunityDocumentInline]
    date_hierarchy = "published_at"

    @admin.display(description="Objeto")
    def title_short(self, obj):
        return obj.title[:100] + "..." if len(obj.title) > 100 else obj.title


@admin.register(OpportunityItem)
class OpportunityItemAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "item_number", "description", "quantity", "estimated_total"]


@admin.register(OpportunityDocument)
class OpportunityDocumentAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "file_name", "processing_status", "ocr_used"]
    list_filter = ["processing_status", "ocr_used"]


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ["document", "chunk_index", "page_number", "token_count"]


@admin.register(ExtractedRequirement)
class ExtractedRequirementAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "category", "requirement", "is_mandatory"]
    list_filter = ["category", "is_mandatory"]


@admin.register(AISummary)
class AISummaryAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "analysis_type", "model_name", "prompt_version", "created_at"]
    list_filter = ["analysis_type", "model_name"]
