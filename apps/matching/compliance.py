"""Compliance check — cross-reference client docs vs opportunity requirements."""
from __future__ import annotations

from datetime import date, timedelta

from apps.clients.models import Client, ClientDocument
from apps.opportunities.models import AISummary, Opportunity

# ── Mapping: requirement category/keywords → client document types ──────

# Maps AI-extracted requirement keywords to ClientDocument.DocType
_KEYWORD_TO_DOCTYPE = {
    "cnd federal": "cnd_federal",
    "certidao negativa federal": "cnd_federal",
    "tributos federais": "cnd_federal",
    "divida ativa": "cnd_federal",
    "receita federal": "cnd_federal",
    "pgfn": "cnd_federal",
    "cnd estadual": "cnd_estadual",
    "certidao estadual": "cnd_estadual",
    "icms": "cnd_estadual",
    "sefaz": "cnd_estadual",
    "cnd municipal": "cnd_municipal",
    "certidao municipal": "cnd_municipal",
    "iss": "cnd_municipal",
    "tributos municipais": "cnd_municipal",
    "fgts": "fgts",
    "crf": "fgts",
    "regularidade fgts": "fgts",
    "cndt": "cndt",
    "debitos trabalhistas": "cndt",
    "certidao trabalhista": "cndt",
    "justica do trabalho": "cndt",
    "balanco": "balanco",
    "balanco patrimonial": "balanco",
    "demonstracoes contabeis": "balanco",
    "atestado": "atestado_tecnico",
    "atestado tecnico": "atestado_tecnico",
    "capacidade tecnica": "atestado_tecnico",
    "contrato social": "contrato_social",
    "ato constitutivo": "contrato_social",
    "estatuto": "contrato_social",
    "procuracao": "procuracao",
    "sicaf": "sicaf",
    "falencia": None,  # can't be auto-matched to a doc type
    "recuperacao judicial": None,
}

# Category-level defaults: standard docs expected per requirement category
_CATEGORY_DEFAULTS = {
    "fiscal": ["cnd_federal", "cnd_estadual", "cnd_municipal", "fgts", "cndt"],
    "juridica": ["contrato_social"],
    "tecnica": ["atestado_tecnico"],
    "economica": ["balanco"],
}

# Links to official portals for each certidão
CERTIDAO_PORTALS = {
    "cnd_federal": {
        "name": "CND Federal (RFB/PGFN)",
        "url": "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PJ/Emitir",
        "desc": "Certidao conjunta de debitos relativos a tributos federais e divida ativa da Uniao",
    },
    "fgts": {
        "name": "CRF/FGTS (Caixa)",
        "url": "https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf",
        "desc": "Certificado de Regularidade do FGTS",
    },
    "cndt": {
        "name": "CNDT (TST)",
        "url": "https://cndt-certidao.tst.jus.br/gerarCertidao.faces",
        "desc": "Certidao Negativa de Debitos Trabalhistas",
    },
    "cnd_estadual": {
        "name": "CND Estadual (Sefaz)",
        "url": "",  # varies by state
        "desc": "Certidao de regularidade fiscal estadual (ICMS)",
    },
    "cnd_municipal": {
        "name": "CND Municipal",
        "url": "",  # varies by city
        "desc": "Certidao de regularidade fiscal municipal (ISS)",
    },
}


def _normalize(text: str) -> str:
    """Lowercase, remove accents for fuzzy matching."""
    import unicodedata
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _match_doc_type(requirement_text: str) -> str | None:
    """Try to map a requirement text to a ClientDocument.DocType."""
    norm = _normalize(requirement_text)
    for keyword, doc_type in _KEYWORD_TO_DOCTYPE.items():
        if keyword in norm:
            return doc_type
    return None


def check_compliance(opportunity: Opportunity, client: Client) -> dict:
    """Cross-reference opportunity requirements with client documents.

    Returns dict with:
      - items: list of {requirement, category, doc_type, status, client_doc, portal}
      - summary: {total, ok, missing, expired, expiring}
      - portals: list of relevant certidão portal links
    """
    today = date.today()
    soon = today + timedelta(days=30)

    # Get client docs indexed by type
    client_docs = {}
    for doc in client.documents.all():
        # Keep the best status doc per type
        existing = client_docs.get(doc.doc_type)
        if not existing or doc.status == "valid":
            client_docs[doc.doc_type] = doc

    # Get requirements from AI analysis
    requirements = list(opportunity.requirements.all())

    # Also parse checklist from AI summary (may have more detail)
    latest_analysis = opportunity.ai_summaries.filter(
        analysis_type="full"
    ).first()
    checklist_items = []
    if latest_analysis and isinstance(latest_analysis.content, dict):
        checklist = latest_analysis.content.get("checklist_habilitacao", {})
        for cat_key, items in checklist.items():
            for item in items:
                text = item.get("requisito", str(item)) if isinstance(item, dict) else str(item)
                checklist_items.append({"category": cat_key, "text": text})

    # Build compliance items from requirements
    items = []
    seen_doc_types = set()

    # From ExtractedRequirement records
    for req in requirements:
        doc_type = _match_doc_type(req.requirement)
        if doc_type:
            seen_doc_types.add(doc_type)
        items.append(_build_item(req.requirement, req.category, doc_type, client_docs, today, soon))

    # From AI checklist (if no ExtractedRequirements)
    if not requirements and checklist_items:
        for ci in checklist_items:
            doc_type = _match_doc_type(ci["text"])
            if doc_type:
                seen_doc_types.add(doc_type)
            items.append(_build_item(ci["text"], ci["category"], doc_type, client_docs, today, soon))

    # If no AI data at all, use category defaults based on modality
    if not items:
        for cat, doc_types in _CATEGORY_DEFAULTS.items():
            for dt in doc_types:
                seen_doc_types.add(dt)
                label = dict(ClientDocument.DocType.choices).get(dt, dt)
                items.append(_build_item(label, cat, dt, client_docs, today, soon))

    # Summary counts
    total = len(items)
    ok = sum(1 for i in items if i["status"] == "ok")
    missing = sum(1 for i in items if i["status"] == "missing")
    expired = sum(1 for i in items if i["status"] == "expired")
    expiring = sum(1 for i in items if i["status"] == "expiring")

    # Relevant portal links
    portals = []
    for dt in sorted(seen_doc_types):
        if dt in CERTIDAO_PORTALS:
            portals.append(CERTIDAO_PORTALS[dt])

    return {
        "items": items,
        "summary": {
            "total": total,
            "ok": ok,
            "missing": missing,
            "expired": expired,
            "expiring": expiring,
        },
        "portals": portals,
    }


def _build_item(requirement_text, category, doc_type, client_docs, today, soon):
    """Build a single compliance check item."""
    client_doc = client_docs.get(doc_type) if doc_type else None

    if not doc_type:
        status = "unknown"
    elif not client_doc:
        status = "missing"
    elif client_doc.status == "expired" or (client_doc.expires_at and client_doc.expires_at < today):
        status = "expired"
    elif client_doc.status == "expiring" or (client_doc.expires_at and client_doc.expires_at < soon):
        status = "expiring"
    else:
        status = "ok"

    portal = CERTIDAO_PORTALS.get(doc_type, {}) if doc_type else {}

    return {
        "requirement": requirement_text,
        "category": category,
        "doc_type": doc_type,
        "doc_type_label": dict(ClientDocument.DocType.choices).get(doc_type, "") if doc_type else "",
        "status": status,
        "client_doc": client_doc,
        "portal_url": portal.get("url", ""),
        "portal_name": portal.get("name", ""),
    }
