"""
Compras.gov.br (Dados Abertos) Connector.

Endpoints reais (Swagger: https://dadosabertos.compras.gov.br/swagger-ui/index.html):
- GET /modulo-pesquisa-preco/v1/contratacoes/publicacao (ou similar paginado)

NOTA: A API de dados abertos do Compras.gov pode ter variações.
Os endpoints abaixo refletem a estrutura documentada no Swagger.
Caso algum endpoint mude, o adapter abstrai a lógica de normalização.
"""
import logging
from datetime import date, datetime

from django.conf import settings

from .base import BaseConnector, NormalizedOpportunity

logger = logging.getLogger(__name__)


class ComprasGovConnector(BaseConnector):
    """Conector para a API de Dados Abertos do Compras.gov.br."""

    def __init__(self):
        super().__init__(
            base_url=settings.COMPRAS_GOV_API_BASE_URL,
            rate_limit_rpm=settings.COMPRAS_GOV_RATE_LIMIT_RPM,
        )

    def _parse_datetime(self, dt_str: str | None) -> str | None:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).isoformat()
        except (ValueError, AttributeError):
            return dt_str

    def _normalize(self, item: dict) -> NormalizedOpportunity:
        """Normalize Compras.gov data to internal format."""
        # Os campos variam conforme o endpoint específico.
        # Esta normalização tenta os nomes mais comuns.
        unidade = item.get("unidadeOrgao", {})
        return NormalizedOpportunity(
            source="compras_gov",
            external_id=f"compras_gov:{item.get('id', item.get('numero', ''))}",
            title=item.get("objeto", item.get("objetoCompra", item.get("descricao", ""))),
            description=item.get("informacaoComplementar", ""),
            modality=self._map_modality(item),
            number=str(item.get("numero", item.get("numeroCompra", ""))),
            process_number=str(item.get("processo", item.get("numeroProcesso", ""))),
            entity_cnpj=item.get("cnpjOrgao", item.get("cnpj", "")),
            entity_name=item.get("nomeOrgao", item.get("nomeUasg", "")),
            entity_uf=unidade.get("ufSigla", "") or item.get("uf", ""),
            entity_city=unidade.get("municipioNome", "") or item.get("municipio", ""),
            published_at=self._parse_datetime(
                item.get("dataPublicacao", item.get("dataResultadoCompra"))
            ),
            proposals_open_at=self._parse_datetime(item.get("dataAbertura")),
            proposals_close_at=self._parse_datetime(item.get("dataEncerramento")),
            deadline=self._parse_datetime(
                item.get("dataEncerramento", item.get("dataEntregaProposta"))
            ),
            estimated_value=item.get("valorEstimado", item.get("valorTotalEstimado")),
            awarded_value=item.get("valorHomologado"),
            is_srp=item.get("srp", False),
            link=item.get("linkEdital", item.get("link", "")),
            raw_data=item,
        )

    def _map_modality(self, item: dict) -> str:
        """Map Compras.gov modality to our enum."""
        modalidade = str(
            item.get("modalidadeLicitacao", item.get("modalidade", ""))
        ).lower()
        if "pregão" in modalidade or "pregao" in modalidade:
            if "eletrônico" in modalidade or "eletronico" in modalidade:
                return "pregao_eletronico"
            return "pregao_presencial"
        if "concorrência" in modalidade or "concorrencia" in modalidade:
            return "concorrencia_eletronica"
        if "dispensa" in modalidade:
            return "dispensa"
        if "inexigibilidade" in modalidade:
            return "inexigibilidade"
        return "other"

    def fetch_opportunities(
        self,
        date_from: date,
        date_to: date,
        **kwargs,
    ) -> list[NormalizedOpportunity]:
        """
        Buscar licitações por período.

        Tenta o endpoint principal e faz fallback para o legado.
        """
        results = []
        page = 1
        page_size = 500

        while True:
            params = {
                "dataInicial": date_from.strftime("%Y-%m-%d"),
                "dataFinal": date_to.strftime("%Y-%m-%d"),
                "pagina": page,
                "tamanhoPagina": page_size,
            }

            try:
                # Tenta endpoint novo
                data = self._get("/modulo-licitacao/v1/licitacoes", params=params)
            except Exception:
                try:
                    # Fallback endpoint alternativo
                    data = self._get("/modulo-compra/v1/compras", params=params)
                except Exception:
                    logger.exception("Compras.gov fetch failed page=%d", page)
                    break

            items = data if isinstance(data, list) else data.get("data", data.get("resultado", []))
            if not items:
                break

            for item in items:
                results.append(self._normalize(item))

            total_pages = data.get("totalPaginas", 1) if isinstance(data, dict) else 1
            if page >= total_pages:
                break
            page += 1

        logger.info(
            "Compras.gov: fetched %d opportunities (%s to %s)",
            len(results), date_from, date_to,
        )
        return results

    def fetch_items(self, opp: NormalizedOpportunity) -> list[dict]:
        """Fetch items — placeholder. Compras.gov pode não expor itens separadamente."""
        # TODO: Implementar quando endpoint de itens for confirmado no Swagger
        return []

    def fetch_documents(self, opp: NormalizedOpportunity) -> list[dict]:
        """Fetch document links — placeholder."""
        link = opp.link
        if link:
            return [{"url": link, "file_name": "edital.pdf", "doc_type": "edital"}]
        return []
