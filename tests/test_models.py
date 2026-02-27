"""Unit tests for domain models."""
import pytest

from apps.clients.models import Client, ClientDocument
from apps.core.utils import dedup_key, normalize_text, object_hash
from apps.opportunities.models import Opportunity, OpportunityItem


class TestCoreUtils:
    def test_normalize_text(self):
        assert normalize_text("  Aquisição  de  Licenças  ") == "aquisicao de licencas"

    def test_dedup_key_deterministic(self):
        k1 = dedup_key("pncp", "id:123")
        k2 = dedup_key("pncp", "id:123")
        assert k1 == k2
        assert len(k1) == 64  # SHA-256 hex

    def test_dedup_key_different_sources(self):
        k1 = dedup_key("pncp", "id:123")
        k2 = dedup_key("compras_gov", "id:123")
        assert k1 != k2

    def test_object_hash(self):
        h1 = object_hash("Aquisição de Licenças")
        h2 = object_hash("aquisicao de licencas")  # normalized should match
        assert h1 == h2


class TestClientModel:
    def test_create_client(self, sample_client):
        assert sample_client.pk is not None
        assert sample_client.name == "Empresa Teste LTDA"
        assert "SP" in sample_client.regions

    def test_client_str(self, sample_client):
        assert "Empresa Teste LTDA" in str(sample_client)

    def test_client_document(self, sample_client_doc):
        assert sample_client_doc.doc_type == ClientDocument.DocType.CND_FEDERAL
        assert sample_client_doc.client.name == "Empresa Teste LTDA"


class TestOpportunityModel:
    def test_create_opportunity(self, sample_opportunity):
        assert sample_opportunity.pk is not None
        assert sample_opportunity.source == Opportunity.Source.PNCP
        assert sample_opportunity.dedup_hash is not None

    def test_opportunity_dedup_unique(self, sample_opportunity, db):
        """Same dedup_hash should violate unique constraint."""
        with pytest.raises(Exception):
            Opportunity.objects.create(
                source="pncp",
                external_id="different",
                dedup_hash=sample_opportunity.dedup_hash,
                object_hash="different",
                title="Different",
                entity_cnpj="000",
                entity_name="Test",
            )

    def test_opportunity_items(self, sample_opportunity):
        item = OpportunityItem.objects.create(
            opportunity=sample_opportunity,
            item_number=1,
            description="Licença Windows",
            quantity=100,
            unit="UN",
            estimated_unit_price=500,
            estimated_total=50000,
        )
        assert item.opportunity == sample_opportunity
        assert sample_opportunity.items.count() == 1
