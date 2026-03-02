"""
PNCP Connector — Portal Nacional de Contratações Públicas.

Endpoints reais (Swagger: https://pncp.gov.br/api/pncp/swagger-ui/index.html):
- GET /v1/contratacoes/publicacao?dataInicial=yyyyMMdd&dataFinal=yyyyMMdd&pagina=1&tamanhoPagina=50
- GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/itens
- GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/arquivos

Endpoints de monitoramento (API CONSULTA):
- GET /v1/contratacoes/atualizacao?dataInicial=yyyyMMdd&dataFinal=yyyyMMdd
- GET /v1/orgaos/{cnpj}/compras/{ano}/{seq} (detalhe)
- GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{item}/resultados
- GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas
- GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos (sem cache)

Limites da API:
- tamanhoPagina máximo = 50 (qualquer valor > 50 retorna 400)
- Sem limite de data range, mas ranges grandes geram milhares de páginas
"""
import logging
from datetime import date, datetime, timedelta
from typing import Callable

import httpx
from django.conf import settings

from .base import BaseConnector, NormalizedOpportunity

logger = logging.getLogger(__name__)

# Mapeamento de modalidadeId PNCP → nosso enum
MODALITY_MAP = {
    1: "leilao",
    2: "dialogo_competitivo",
    3: "concurso",
    4: "concorrencia_eletronica",
    5: "concorrencia_presencial",
    6: "pregao_eletronico",
    7: "pregao_presencial",
    8: "dispensa",
    9: "inexigibilidade",
    10: "other",
    11: "other",
    12: "credenciamento",
    13: "leilao",
}

# Modalidades mais relevantes para licitações de serviços/produtos
# (pregão eletrônico + concorrência são ~80% do volume útil)
DEFAULT_MODALITIES = [6, 4, 8, 5, 9, 12]  # pregao_e, concorrencia_e, dispensa, concorrencia_p, inex, cred
ALL_MODALITIES = list(MODALITY_MAP.keys())


class PNCPConnector(BaseConnector):
    """Conector para a API pública do PNCP."""

    def __init__(self):
        super().__init__(
            base_url=settings.PNCP_API_BASE_URL,
            rate_limit_rpm=settings.PNCP_RATE_LIMIT_RPM,
        )
        self._consulta_client = httpx.Client(
            base_url=settings.PNCP_CONSULTA_API_BASE_URL,
            timeout=30.0,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "LicitaAI/1.0"},
        )

    def close(self):
        self.client.close()
        self._consulta_client.close()

    def _parse_datetime(self, dt_str: str | None) -> str | None:
        """Parse PNCP datetime strings."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).isoformat()
        except (ValueError, AttributeError):
            return dt_str

    def _build_external_id(self, item: dict) -> str:
        """Build unique external ID from PNCP data."""
        cnpj = item.get("orgaoEntidade", {}).get("cnpj", "")
        ano = item.get("anoCompra", "")
        seq = item.get("sequencialCompra", "")
        return f"pncp:{cnpj}:{ano}:{seq}"

    def _normalize(self, item: dict) -> NormalizedOpportunity:
        """Normalize a PNCP contratacao to our internal format."""
        orgao = item.get("orgaoEntidade", {})
        unidade = item.get("unidadeOrgao", {})
        modalidade_id = item.get("modalidadeId", 0)

        return NormalizedOpportunity(
            source="pncp",
            external_id=self._build_external_id(item),
            title=item.get("objetoCompra") or "",
            description=item.get("informacaoComplementar") or "",
            modality=MODALITY_MAP.get(modalidade_id, "other"),
            number=item.get("numeroCompra") or "",
            process_number=item.get("numeroProcesso") or "",
            entity_cnpj=orgao.get("cnpj") or "",
            entity_name=orgao.get("razaoSocial") or "",
            entity_uf=unidade.get("ufSigla") or "",
            entity_city=unidade.get("municipioNome") or "",
            published_at=self._parse_datetime(item.get("dataPublicacaoPncp")),
            proposals_open_at=self._parse_datetime(item.get("dataAberturaProposta")),
            proposals_close_at=self._parse_datetime(item.get("dataEncerramentoProposta")),
            deadline=self._parse_datetime(
                item.get("dataEncerramentoProposta") or item.get("dataAberturaProposta")
            ),
            estimated_value=item.get("valorTotalEstimado"),
            awarded_value=item.get("valorTotalHomologado"),
            is_srp=bool(item.get("srp", False)),
            link=item.get("linkSistemaOrigem") or "",
            raw_data=item,
        )

    def fetch_opportunities(
        self,
        date_from: date,
        date_to: date,
        uf: str | None = None,
        keyword: str | None = None,
        modalities: list[int] | None = None,
        max_pages: int = 0,
        on_progress: Callable[[str], None] | None = None,
    ) -> list[NormalizedOpportunity]:
        """
        Buscar contratações publicadas no período.

        Endpoint real: GET /v1/contratacoes/publicacao
        API exige codigoModalidadeContratacao; tamanhoPagina máx = 50.

        Args:
            modalities: lista de IDs de modalidade (default: DEFAULT_MODALITIES)
            max_pages: limite de páginas por modalidade (0 = sem limite)
            on_progress: callback para log de progresso
        """
        results = []
        modalities_to_fetch = modalities or DEFAULT_MODALITIES

        def _log(msg: str):
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        for modality_id in modalities_to_fetch:
            mod_name = MODALITY_MAP.get(modality_id, "?")
            page = 1
            mod_count = 0

            while True:
                params = {
                    "dataInicial": date_from.strftime("%Y%m%d"),
                    "dataFinal": date_to.strftime("%Y%m%d"),
                    "codigoModalidadeContratacao": modality_id,
                    "pagina": page,
                    "tamanhoPagina": 50,
                }
                if uf:
                    params["uf"] = uf

                try:
                    data = self._get("/v1/contratacoes/publicacao", params=params)
                except Exception:
                    logger.warning("PNCP fetch failed modality=%d (%s) page=%d", modality_id, mod_name, page)
                    break

                items = data.get("data", [])
                if not items:
                    break

                for item in items:
                    results.append(self._normalize(item))
                mod_count += len(items)

                total_pages = data.get("totalPaginas", 1)
                total_records = data.get("totalRegistros", "?")

                if page == 1:
                    _log(f"  Modalidade {modality_id} ({mod_name}): {total_records} registros, {total_pages} paginas")

                if page >= total_pages:
                    break
                if max_pages and page >= max_pages:
                    _log(f"  Modalidade {modality_id}: parou na pagina {page}/{total_pages} (max_pages={max_pages})")
                    break
                page += 1

        # Filtro por keyword (pós-fetch, pois a API não tem param 'q')
        if keyword:
            kw = keyword.lower()
            results = [r for r in results if kw in r.title.lower() or kw in r.description.lower()]

        _log(f"PNCP: fetched {len(results)} opportunities ({date_from} to {date_to})")
        return results

    def fetch_items(self, opp: NormalizedOpportunity) -> list[dict]:
        """
        Buscar itens de uma contratação.

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens
        """
        raw = opp.raw_data
        cnpj = raw.get("orgaoEntidade", {}).get("cnpj", "")
        ano = raw.get("anoCompra", "")
        seq = raw.get("sequencialCompra", "")

        if not all([cnpj, ano, seq]):
            return []

        try:
            data = self._get(f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens")
        except Exception:
            logger.exception("PNCP items fetch failed for %s", opp.external_id)
            return []

        items = data if isinstance(data, list) else data.get("data", data.get("itens", []))
        return [
            {
                "item_number": it.get("numeroItem", idx + 1),
                "description": it.get("descricao", ""),
                "quantity": it.get("quantidade"),
                "unit": it.get("unidadeMedida", ""),
                "estimated_unit_price": it.get("valorUnitarioEstimado"),
                "estimated_total": it.get("valorTotal"),
                "material_or_service": it.get("materialOuServico", ""),
                "raw_data": it,
            }
            for idx, it in enumerate(items)
        ]

    def fetch_documents(self, opp: NormalizedOpportunity) -> list[dict]:
        """
        Buscar anexos/documentos de uma contratação.

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos
        """
        raw = opp.raw_data
        cnpj = raw.get("orgaoEntidade", {}).get("cnpj", "")
        ano = raw.get("anoCompra", "")
        seq = raw.get("sequencialCompra", "")

        if not all([cnpj, ano, seq]):
            return []

        try:
            data = self._get(f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos")
        except Exception:
            logger.exception("PNCP documents fetch failed for %s", opp.external_id)
            return []

        docs = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "url": doc.get("uri", doc.get("url", "")),
                "file_name": doc.get("nomeArquivo", ""),
                "doc_type": doc.get("tipoDocumentoNome", ""),
            }
            for doc in docs
        ]

    # ── Monitoring methods ─────────────────────────────────

    def fetch_updated_procurement_ids(
        self, date_from: date, date_to: date
    ) -> list[dict]:
        """
        List procurements updated in the period via API CONSULTA.

        Endpoint: GET /v1/contratacoes/atualizacao
        Returns list of dicts with cnpj, ano, seq, external_id.
        """
        results = []
        page = 1

        while True:
            params = {
                "dataInicial": date_from.strftime("%Y%m%d"),
                "dataFinal": date_to.strftime("%Y%m%d"),
                "pagina": page,
                "tamanhoPagina": 50,
            }

            try:
                data = self._get_nocache(
                    "/v1/contratacoes/atualizacao",
                    params=params,
                    client=self._consulta_client,
                )
            except Exception:
                logger.warning(
                    "PNCP atualizacao fetch failed page=%d", page, exc_info=True,
                )
                break

            items = data.get("data", [])
            if not items:
                break

            for item in items:
                orgao = item.get("orgaoEntidade", {})
                cnpj = orgao.get("cnpj", "")
                ano = item.get("anoCompra", "")
                seq = item.get("sequencialCompra", "")
                if cnpj and ano and seq:
                    results.append({
                        "cnpj": cnpj,
                        "ano": ano,
                        "seq": seq,
                        "external_id": f"pncp:{cnpj}:{ano}:{seq}",
                    })

            total_pages = data.get("totalPaginas", 1)
            if page >= total_pages:
                break
            page += 1

        logger.info(
            "PNCP atualizacao: %d updated procurements (%s to %s)",
            len(results), date_from, date_to,
        )
        return results

    def fetch_opportunity_detail(self, cnpj: str, ano: str, seq: str) -> dict:
        """
        Fetch current detail of a procurement (no cache).

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}
        """
        try:
            return self._get_nocache(
                f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}",
                client=self._consulta_client,
            )
        except Exception:
            logger.exception("PNCP detail fetch failed: %s/%s/%s", cnpj, ano, seq)
            return {}

    def fetch_results(self, cnpj: str, ano: str, seq: str) -> list[dict]:
        """
        Fetch results for each item of a procurement.

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{item}/resultados
        """
        all_results = []
        try:
            items_data = self._get_nocache(
                f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens",
                client=self._consulta_client,
            )
        except Exception:
            logger.exception("PNCP items fetch (for results) failed: %s/%s/%s", cnpj, ano, seq)
            return []

        items = items_data if isinstance(items_data, list) else items_data.get("data", [])
        for item in items:
            num = item.get("numeroItem")
            if not num:
                continue
            try:
                result_data = self._get_nocache(
                    f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{num}/resultados",
                    client=self._consulta_client,
                )
                results = result_data if isinstance(result_data, list) else result_data.get("data", [])
                for r in results:
                    r["_itemNumero"] = num
                all_results.extend(results)
            except Exception:
                logger.warning(
                    "PNCP results fetch failed: %s/%s/%s item %s",
                    cnpj, ano, seq, num,
                )
        return all_results

    def fetch_atas(self, cnpj: str, ano: str, seq: str) -> list[dict]:
        """
        Fetch atas de registro de preço.

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas
        """
        try:
            data = self._get_nocache(
                f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas",
                client=self._consulta_client,
            )
            return data if isinstance(data, list) else data.get("data", [])
        except Exception:
            logger.exception("PNCP atas fetch failed: %s/%s/%s", cnpj, ano, seq)
            return []

    def fetch_documents_fresh(self, cnpj: str, ano: str, seq: str) -> list[dict]:
        """
        Fetch documents WITHOUT cache (for monitoring).

        Endpoint: GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos
        """
        try:
            data = self._get_nocache(
                f"/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos",
                client=self._consulta_client,
            )
            docs = data if isinstance(data, list) else data.get("data", [])
            return [
                {
                    "url": doc.get("uri", doc.get("url", "")),
                    "file_name": doc.get("nomeArquivo", ""),
                    "doc_type": doc.get("tipoDocumentoNome", ""),
                }
                for doc in docs
            ]
        except Exception:
            logger.exception("PNCP fresh docs fetch failed: %s/%s/%s", cnpj, ano, seq)
            return []
