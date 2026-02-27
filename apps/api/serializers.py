"""DRF serializers — base para futura integração."""
from rest_framework import serializers

from apps.clients.models import Client, ClientDocument
from apps.matching.models import Match
from apps.opportunities.models import (
    AISummary,
    Opportunity,
    OpportunityDocument,
    OpportunityItem,
)


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            "id", "name", "cnpj", "trade_name", "email", "phone",
            "regions", "keywords", "categories", "min_margin_pct",
            "max_value", "is_active", "created_at",
        ]


class ClientDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientDocument
        fields = [
            "id", "client", "doc_type", "description", "file", "url",
            "issued_at", "expires_at", "status",
        ]


class OpportunityItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpportunityItem
        fields = [
            "id", "item_number", "description", "quantity", "unit",
            "estimated_unit_price", "estimated_total", "material_or_service",
        ]


class OpportunityDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpportunityDocument
        fields = [
            "id", "original_url", "file_name", "file_size", "mime_type",
            "doc_type", "processing_status", "ocr_used",
        ]


class AISummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = AISummary
        fields = [
            "id", "analysis_type", "content", "prompt_version",
            "model_name", "tokens_used", "processing_time_ms", "created_at",
        ]


class MatchSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)

    class Meta:
        model = Match
        fields = [
            "id", "client", "client_name", "score", "justification",
            "missing_docs", "missing_capabilities", "evidence",
            "prompt_version", "created_at",
        ]


class OpportunitySerializer(serializers.ModelSerializer):
    items = OpportunityItemSerializer(many=True, read_only=True)
    documents = OpportunityDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Opportunity
        fields = [
            "id", "source", "external_id", "title", "description",
            "modality", "number", "entity_cnpj", "entity_name",
            "entity_uf", "entity_city", "published_at", "proposals_open_at",
            "proposals_close_at", "deadline", "estimated_value",
            "awarded_value", "is_srp", "status", "link",
            "items", "documents", "created_at",
        ]


class OpportunityDetailSerializer(OpportunitySerializer):
    ai_summaries = AISummarySerializer(many=True, read_only=True)
    matches = MatchSerializer(many=True, read_only=True)

    class Meta(OpportunitySerializer.Meta):
        fields = OpportunitySerializer.Meta.fields + ["ai_summaries", "matches"]
