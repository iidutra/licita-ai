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
        whatsapp_phone="5511999999999",
        notify_whatsapp=True,
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
def monitored_opportunity(db):
    """Opportunity with raw_data populated for monitoring tests."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.core.utils import dedup_key, object_hash

    title = "Pregão Eletrônico para serviços de TI"
    return Opportunity.objects.create(
        source=Opportunity.Source.PNCP,
        external_id="pncp:00394460000141:2024:042",
        dedup_hash=dedup_key("pncp", "pncp:00394460000141:2024:042"),
        object_hash=object_hash(title),
        title=title,
        description="Contratação de serviços de tecnologia da informação",
        modality=Opportunity.Modality.PREGAO_ELETRONICO,
        entity_cnpj="00394460000141",
        entity_name="Ministério da Gestão",
        entity_uf="DF",
        estimated_value=500000,
        status=Opportunity.Status.ANALYZING,
        deadline=timezone.now() + timedelta(days=30),
        raw_data={
            "orgaoEntidade": {"cnpj": "00394460000141", "razaoSocial": "Ministério da Gestão"},
            "anoCompra": 2024,
            "sequencialCompra": 42,
            "situacaoCompraId": 1,
            "situacaoCompraNome": "Divulgada",
            "dataEncerramentoProposta": "2026-04-01T18:00:00-03:00",
            "valorTotalEstimado": 500000,
            "valorTotalHomologado": None,
            "_monitored_results": [],
            "_monitored_atas": [],
        },
    )


@pytest.fixture
def opportunity_with_dates(db, sample_client):
    """Opportunity with proposals_open_at, deadline, and a matching client."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.core.utils import dedup_key, object_hash
    from apps.matching.models import Match

    now = timezone.now()
    title = "Pregão Eletrônico - Serviços de Cloud"
    opp = Opportunity.objects.create(
        source=Opportunity.Source.PNCP,
        external_id="pncp:99999999000100:2024:099",
        dedup_hash=dedup_key("pncp", "pncp:99999999000100:2024:099"),
        object_hash=object_hash(title),
        title=title,
        description="Contratação de serviços de computação em nuvem",
        modality=Opportunity.Modality.PREGAO_ELETRONICO,
        entity_cnpj="99999999000100",
        entity_name="Ministério da Ciência",
        entity_uf="DF",
        number="PE 99/2024",
        estimated_value=300000,
        status=Opportunity.Status.ANALYZING,
        proposals_open_at=now + timedelta(hours=24),
        deadline=now + timedelta(days=7),
    )
    Match.objects.create(
        opportunity=opp,
        client=sample_client,
        score=75,
        justification="Boa aderência ao perfil",
    )
    return opp


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
