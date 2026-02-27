"""Tests for API connectors — unit tests with mocked HTTP."""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from apps.connectors.normalizer import persist_opportunity
from apps.connectors.pncp import PNCPConnector


MOCK_PNCP_RESPONSE = {
    "totalRegistros": 1,
    "totalPaginas": 1,
    "paginaAtual": 1,
    "data": [
        {
            "orgaoEntidade": {
                "cnpj": "00394460000141",
                "razaoSocial": "Ministério da Economia",
                "uf": "DF",
                "municipio": {"nomeIbge": "Brasília"},
            },
            "anoCompra": "2024",
            "sequencialCompra": "00001",
            "numeroCompra": "PE 01/2024",
            "modalidadeId": 6,
            "objetoCompra": "Aquisição de equipamentos de TI",
            "informacaoComplementar": "Servidores e switches",
            "srp": False,
            "dataPublicacaoPncp": "2024-01-15T10:00:00Z",
            "dataAberturaProposta": "2024-02-01T09:00:00Z",
            "dataEncerramentoProposta": "2024-02-15T18:00:00Z",
            "valorTotalEstimado": 500000.00,
            "linkSistemaOrigem": "https://comprasnet.gov.br/...",
        }
    ],
}


class TestPNCPConnector:
    @patch("apps.connectors.pncp.PNCPConnector._get")
    def test_fetch_opportunities(self, mock_get):
        mock_get.return_value = MOCK_PNCP_RESPONSE

        connector = PNCPConnector()
        results = connector.fetch_opportunities(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
        )

        assert len(results) == 1
        opp = results[0]
        assert opp.source == "pncp"
        assert opp.title == "Aquisição de equipamentos de TI"
        assert opp.entity_uf == "DF"
        assert opp.modality == "pregao_eletronico"
        assert opp.estimated_value == 500000.00

    @patch("apps.connectors.pncp.PNCPConnector._get")
    def test_fetch_with_keyword_filter(self, mock_get):
        mock_get.return_value = MOCK_PNCP_RESPONSE

        connector = PNCPConnector()
        results = connector.fetch_opportunities(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
            keyword="equipamentos",
        )
        assert len(results) == 1

        results = connector.fetch_opportunities(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
            keyword="xyznotfound",
        )
        assert len(results) == 0


class TestNormalizer:
    @patch("apps.connectors.pncp.PNCPConnector._get")
    def test_persist_idempotent(self, mock_get, db):
        """Persisting the same opportunity twice should be idempotent."""
        mock_get.return_value = MOCK_PNCP_RESPONSE

        connector = PNCPConnector()
        results = connector.fetch_opportunities(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 1, 31),
        )

        opp1, created1 = persist_opportunity(results[0])
        assert created1 is True

        opp2, created2 = persist_opportunity(results[0])
        assert created2 is False
        assert opp1.pk == opp2.pk
