"""
Compras.gov.br (Dados Abertos) Connector.

Swagger: https://dadosabertos.compras.gov.br/swagger-ui/index.html

Endpoints (Lei 14.133/2021):
- GET /modulo-contratacoes/1_consultarContratacoes_PNCP_14133
  params: dataPublicacaoPncpInicial, dataPublicacaoPncpFinal (YYYY-MM-DD),
          codigoModalidade (required), pagina, tamanhoPagina
"""
import logging
from datetime import date, datetime

import httpx
from django.conf import settings

from .base import BaseConnector, NormalizedOpportunity

logger = logging.getLogger(__name__)

# Modalidades disponíveis na API Compras.gov
COMPRAS_GOV_MODALITIES = {
    1: "leilao",
    2: "dialogo_competitivo",
    3: "concurso",
    4: "concorrencia_eletronica",
    5: "concorrencia_presencial",
    6: "pregao_eletronico",
    7: "pregao_presencial",
    8: "dispensa",
    9: "inexigibilidade",
    12: "credenciamento",
    13: "leilao",
}

DEFAULT_MODALITIES = [6, 4, 8, 5, 9, 12]


class ComprasGovConnector(BaseConnector):
    """Conector para a API de Dados Abertos do Compras.gov.br."""

    def __init__(self):
        super().__init__(
            base_url=settings.COMPRAS_GOV_API_BASE_URL,
            rate_limit_rpm=settings.COMPRAS_GOV_RATE_LIMIT_RPM,
        )
        # Compras.gov may have SSL issues, increase timeout
        self.client = httpx.Client(
            base_url=settings.COMPRAS_GOV_API_BASE_URL,
            timeout=60.0,
            follow_redirects=True,
            verify=False,
            headers={"Accept": "application/json", "User-Agent": "LicitaAI/1.0"},
        )

    def _parse_datetime(self, dt_str: str | None) -> str | None:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).isoformat()
        except (ValueError, AttributeError):
            return dt_str

    def _build_pncp_link(self, item: dict) -> str:
        """Build PNCP portal link from Compras.gov data."""
        cnpj = item.get("orgaoEntidadeCnpj", "")
        ano = item.get("anoCompraPncp", "") or item.get("anoCompra", "")
        seq = item.get("sequencialCompraPncp", "") or item.get("sequencialCompra", "")
        if cnpj and ano and seq:
            return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
        return ""

    def _normalize(self, item: dict) -> NormalizedOpportunity:
        """Normalize Compras.gov data to internal format."""
        modalidade_id = item.get("modalidadeIdPncp", 0)
        modality = COMPRAS_GOV_MODALITIES.get(modalidade_id, "other")

        return NormalizedOpportunity(
            source="compras_gov",
            external_id=f"compras_gov:{item.get('idCompra', '')}",
            title=item.get("objetoCompra", ""),
            description=item.get("informacaoComplementar") or "",
            modality=modality,
            number=str(item.get("numeroCompra", "")),
            process_number=str(item.get("processo", "")),
            entity_cnpj=item.get("orgaoEntidadeCnpj", ""),
            entity_name=item.get("orgaoEntidadeRazaoSocial", ""),
            entity_uf=item.get("unidadeOrgaoUfSigla", ""),
            entity_city=item.get("unidadeOrgaoMunicipioNome", ""),
            published_at=self._parse_datetime(item.get("dataPublicacaoPncp")),
            proposals_open_at=self._parse_datetime(item.get("dataAberturaPropostaPncp")),
            proposals_close_at=self._parse_datetime(item.get("dataEncerramentoPropostaPncp")),
            deadline=self._parse_datetime(
                item.get("dataEncerramentoPropostaPncp") or item.get("dataAberturaPropostaPncp")
            ),
            estimated_value=item.get("valorTotalEstimado"),
            awarded_value=item.get("valorTotalHomologado"),
            is_srp=bool(item.get("srp", False)),
            link=item.get("linkSistemaOrigem") or self._build_pncp_link(item),
            raw_data=item,
        )

    def fetch_opportunities(
        self,
        date_from: date,
        date_to: date,
        modalities: list[int] | None = None,
        **kwargs,
    ) -> list[NormalizedOpportunity]:
        """Buscar contratações por período via API Compras.gov."""
        results = []
        modalities_to_fetch = modalities or DEFAULT_MODALITIES

        for modality_id in modalities_to_fetch:
            mod_name = COMPRAS_GOV_MODALITIES.get(modality_id, "?")
            page = 1

            while True:
                params = {
                    "dataPublicacaoPncpInicial": date_from.strftime("%Y-%m-%d"),
                    "dataPublicacaoPncpFinal": date_to.strftime("%Y-%m-%d"),
                    "codigoModalidade": modality_id,
                    "pagina": page,
                    "tamanhoPagina": 50,
                }

                try:
                    data = self._get(
                        "/modulo-contratacoes/1_consultarContratacoes_PNCP_14133",
                        params=params,
                    )
                except Exception:
                    logger.warning(
                        "Compras.gov fetch failed modality=%d (%s) page=%d",
                        modality_id, mod_name, page, exc_info=True,
                    )
                    break

                items = data.get("resultado", [])
                if not items:
                    break

                for item in items:
                    results.append(self._normalize(item))

                total_pages = data.get("totalPaginas", 1)
                if page == 1:
                    total_records = data.get("totalRegistros", "?")
                    logger.info(
                        "  Compras.gov mod %d (%s): %s registros, %s paginas",
                        modality_id, mod_name, total_records, total_pages,
                    )

                if page >= total_pages:
                    break
                page += 1

        logger.info(
            "Compras.gov: fetched %d opportunities (%s to %s)",
            len(results), date_from, date_to,
        )
        return results

    def fetch_items(self, opp: NormalizedOpportunity) -> list[dict]:
        """Fetch items — not available in Compras.gov API."""
        return []

    def fetch_documents(self, opp: NormalizedOpportunity) -> list[dict]:
        """Fetch real document files via PNCP API."""
        raw = opp.raw_data
        cnpj = raw.get("orgaoEntidadeCnpj", "")
        ano = raw.get("anoCompraPncp", "") or raw.get("anoCompra", "")
        seq = raw.get("sequencialCompraPncp", "") or raw.get("sequencialCompra", "")

        if not all([cnpj, ano, seq]):
            # Fallback: return portal link if we can't fetch real docs
            if opp.link:
                return [{"url": opp.link, "file_name": "edital.pdf", "doc_type": "edital"}]
            return []

        try:
            pncp_client = httpx.Client(
                base_url=settings.PNCP_API_BASE_URL.replace("/api/consulta", "/pncp-api"),
                timeout=30.0,
                follow_redirects=True,
                headers={"Accept": "application/json", "User-Agent": "LicitaAI/1.0"},
            )
            resp = pncp_client.get(f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos")
            resp.raise_for_status()
            data = resp.json()
            pncp_client.close()
        except Exception:
            logger.warning(
                "Compras.gov: PNCP doc fetch failed for %s/%s/%s",
                cnpj, ano, seq, exc_info=True,
            )
            if opp.link:
                return [{"url": opp.link, "file_name": "edital.pdf", "doc_type": "edital"}]
            return []

        docs = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "url": doc.get("uri", doc.get("url", "")),
                "file_name": doc.get("nomeArquivo", ""),
                "doc_type": doc.get("tipoDocumentoNome", ""),
            }
            for doc in docs
            if doc.get("uri") or doc.get("url")
        ]
