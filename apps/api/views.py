"""DRF viewsets — base pronta para futura integração."""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.clients.models import Client
from apps.opportunities.models import Opportunity

from .serializers import (
    ClientSerializer,
    OpportunityDetailSerializer,
    OpportunitySerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.filter(is_active=True)
    serializer_class = ClientSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ["name", "cnpj", "trade_name"]
    filterset_fields = ["regions", "is_active"]


class OpportunityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Opportunity.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "entity_name"]
    filterset_fields = ["source", "status", "modality", "entity_uf"]
    ordering_fields = ["published_at", "deadline", "estimated_value"]
    ordering = ["-published_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return OpportunityDetailSerializer
        return OpportunitySerializer

    @action(detail=True, methods=["post"])
    def run_ai(self, request, pk=None):
        """POST /api/opportunities/{id}/run_ai/ {"analysis_type": "full"}"""
        from apps.ai_engine.tasks import run_ai_analysis

        analysis_type = request.data.get("analysis_type", "full")
        run_ai_analysis.delay(str(pk), analysis_type)
        return Response({"status": "enqueued", "analysis_type": analysis_type})

    @action(detail=True, methods=["post"])
    def run_matching(self, request, pk=None):
        """POST /api/opportunities/{id}/run_matching/ {"client_id": "uuid"}"""
        from apps.matching.tasks import run_matching

        client_id = request.data.get("client_id")
        if not client_id:
            return Response({"error": "client_id is required"}, status=400)
        run_matching.delay(str(pk), client_id)
        return Response({"status": "enqueued", "client_id": client_id})
