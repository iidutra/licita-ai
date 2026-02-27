"""Shared fixtures for tests."""
import pytest
from django.test import Client as HttpClient

from apps.clients.models import Client, ClientDocument
from apps.opportunities.models import Opportunity


@pytest.fixture
def auth_client(db, django_user_model):
    """Authenticated HTTP client."""
    user = django_user_model.objects.create_user(username="testuser", password="testpass123")
    client = HttpClient()
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def sample_client(db):
    """Sample client for testing."""
    return Client.objects.create(
        name="Empresa Teste LTDA",
        cnpj="12.345.678/0001-99",
        trade_name="Teste Tech",
        email="contato@teste.com",
        regions=["SP", "RJ"],
        keywords=["tecnologia", "software", "TI"],
        categories=["Desenvolvimento de Software"],
        min_margin_pct=10,
        is_active=True,
    )


@pytest.fixture
def sample_client_doc(db, sample_client):
    """Sample client document."""
    return ClientDocument.objects.create(
        client=sample_client,
        doc_type=ClientDocument.DocType.CND_FEDERAL,
        status=ClientDocument.DocStatus.VALID,
    )


@pytest.fixture
def sample_opportunity(db):
    """Sample opportunity for testing."""
    from apps.core.utils import dedup_key, object_hash

    title = "Aquisição de licenças de software"
    return Opportunity.objects.create(
        source=Opportunity.Source.PNCP,
        external_id="pncp:12345678000199:2024:001",
        dedup_hash=dedup_key("pncp", "pncp:12345678000199:2024:001"),
        object_hash=object_hash(title),
        title=title,
        description="Aquisição de licenças de software para o órgão",
        modality=Opportunity.Modality.PREGAO_ELETRONICO,
        entity_cnpj="12345678000199",
        entity_name="Ministério da Economia",
        entity_uf="DF",
        estimated_value=150000,
        status=Opportunity.Status.NEW,
    )
