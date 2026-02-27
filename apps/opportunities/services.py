"""Pure functions that transform model data into view-ready structures."""
from __future__ import annotations

import re
from decimal import Decimal

from django.utils import timezone

from .parser import (
    _text_from_content,
    extract_recommendation,
    format_brl,
    md_to_html,
    parse_ai_sections,
)


# ---------------------------------------------------------------------------
# Smart chips
# ---------------------------------------------------------------------------
def derive_smart_chips(opp) -> list[dict]:
    """Return ``[{label, color, icon}]`` derived from opportunity metadata."""
    chips: list[dict] = []

    # Status
    STATUS_CHIP = {
        "new": ("Novo", "primary", "bi-circle-fill"),
        "analyzing": ("Em Analise", "warning", "bi-hourglass-split"),
        "eligible": ("Apto", "success", "bi-check-circle-fill"),
        "discarded": ("Descartado", "secondary", "bi-x-circle"),
        "submitted": ("Proposta Enviada", "info", "bi-send-fill"),
    }
    s = STATUS_CHIP.get(opp.status)
    if s:
        chips.append({"label": s[0], "color": s[1], "icon": s[2]})

    # Modality
    if opp.modality and opp.modality != "other":
        chips.append({"label": opp.get_modality_display(), "color": "dark", "icon": ""})

    # Value threshold
    if opp.estimated_value:
        if opp.estimated_value >= 10_000_000:
            chips.append({"label": "Alto valor", "color": "danger", "icon": "bi-graph-up-arrow"})
        elif opp.estimated_value >= 1_000_000:
            chips.append({"label": "Valor expressivo", "color": "warning", "icon": "bi-graph-up-arrow"})

    # Deadline urgency
    if opp.deadline:
        delta = (opp.deadline - timezone.now()).total_seconds()
        if 0 < delta < 3 * 86400:
            chips.append({"label": "Prazo curto", "color": "danger", "icon": "bi-alarm"})

    if opp.is_srp:
        chips.append({"label": "SRP", "color": "info", "icon": ""})

    if opp.entity_uf:
        chips.append({"label": opp.entity_uf, "color": "secondary", "icon": ""})

    if opp.source:
        chips.append({"label": opp.get_source_display(), "color": "secondary", "icon": ""})

    return chips


# ---------------------------------------------------------------------------
# Go / No-Go
# ---------------------------------------------------------------------------
def extract_go_nogo(ai_summaries) -> str | None:
    """Scan summaries for recommendation. Returns go/go_ressalvas/nogo/None."""
    for s in ai_summaries:
        rec = extract_recommendation(s.content)
        if rec:
            return rec
    return None


# ---------------------------------------------------------------------------
# Timeline & countdown
# ---------------------------------------------------------------------------
def compute_timeline(opp) -> dict:
    """Deadline info, urgency colour, and progress percentage."""
    empty = {
        "deadline": None, "deadline_iso": None,
        "delta_days": None, "delta_hours": None,
        "urgency": "gray", "progress_pct": 0,
    }
    if not opp.deadline:
        return empty

    now = timezone.now()
    total_sec = int((opp.deadline - now).total_seconds())
    days = max(total_sec // 86400, 0)
    hours = max((total_sec % 86400) // 3600, 0)

    if total_sec <= 0:
        urgency = "expired"
    elif days < 3:
        urgency = "red"
    elif days < 7:
        urgency = "yellow"
    else:
        urgency = "green"

    # Progress bar: from published_at to deadline
    progress_pct = 0
    start = opp.published_at or opp.created_at
    if start and opp.deadline:
        total_span = (opp.deadline - start).total_seconds()
        elapsed = (now - start).total_seconds()
        if total_span > 0:
            progress_pct = min(max(int(elapsed / total_span * 100), 0), 100)

    return {
        "deadline": opp.deadline,
        "deadline_iso": opp.deadline.isoformat(),
        "delta_days": days,
        "delta_hours": hours,
        "urgency": urgency,
        "progress_pct": progress_pct,
    }


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------
_URGENCY_HEX = {
    "green": "#059669", "yellow": "#d97706", "red": "#dc2626",
    "expired": "#6b7280", "gray": "#6b7280",
}


def build_kpi_cards(opp, items, matches) -> list[dict]:
    """Four KPI card dicts for the dashboard header."""
    best_score = None
    if matches:
        scores = [m.score for m in matches if m.score is not None]
        if scores:
            best_score = max(scores)

    tl = compute_timeline(opp)
    if tl["deadline"]:
        prazo_label = "Encerrado" if tl["urgency"] == "expired" else f"{tl['delta_days']}d {tl['delta_hours']}h"
    else:
        prazo_label = "\u2014"

    item_count = len(items) if hasattr(items, "__len__") else items.count()

    return [
        {
            "title": "Valor Estimado",
            "value": format_brl(opp.estimated_value),
            "icon": "bi-cash-stack",
            "color": "#059669",
        },
        {
            "title": "Prazo Final",
            "value": prazo_label,
            "icon": "bi-clock",
            "color": _URGENCY_HEX.get(tl["urgency"], "#6b7280"),
        },
        {
            "title": "Itens",
            "value": str(item_count),
            "icon": "bi-list-ol",
            "color": "#1a56db",
        },
        {
            "title": "Melhor Match",
            "value": f"{best_score}/100" if best_score is not None else "\u2014",
            "icon": "bi-bullseye",
            "color": "#7c3aed" if best_score and best_score >= 70 else "#d97706",
        },
    ]


# ---------------------------------------------------------------------------
# Risks
# ---------------------------------------------------------------------------
def aggregate_risks(ai_summaries) -> list[dict]:
    """Collect risk dicts from ``full``-type summaries."""
    risks: list[dict] = []
    for s in ai_summaries:
        if s.analysis_type != "full" or not isinstance(s.content, dict):
            continue
        for r in s.content.get("riscos", []):
            if isinstance(r, dict):
                risks.append({
                    "tipo": r.get("tipo", "Risco"),
                    "descricao": r.get("descricao", ""),
                    "severidade": r.get("severidade", "media"),
                    "evidencia": r.get("evidencia", {}),
                })
    return risks


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------
def build_action_checklist(requirements) -> list[dict]:
    """Group requirements by category for the checklist tab."""
    groups: dict[str, list[dict]] = {}
    for req in requirements:
        cat = req.get_category_display()
        groups.setdefault(cat, []).append({
            "id": str(req.pk),
            "text": req.requirement,
            "mandatory": req.is_mandatory,
        })
    return [{"category": cat, "items": items} for cat, items in groups.items()]


# ---------------------------------------------------------------------------
# Summary sections (server-rendered HTML)
# ---------------------------------------------------------------------------
def build_summary_context(ai_summaries) -> dict:
    """Return summary_sections (list) and resumo_html (str) for template."""
    summary_sections: list[dict] = []
    resumo_html = ""

    for s in ai_summaries:
        if s.analysis_type == "summary" and not summary_sections:
            text = _text_from_content(s.content)
            summary_sections = parse_ai_sections(text)
            if not summary_sections and text:
                summary_sections = [{"title": "Resumo Executivo", "html": md_to_html(text)}]
        elif s.analysis_type == "full" and not resumo_html:
            content = s.content
            if isinstance(content, dict):
                raw = content.get("resumo", "") or _text_from_content(content)
            else:
                raw = _text_from_content(content)
            resumo_html = md_to_html(raw)

    return {
        "summary_sections": summary_sections,
        "resumo_html": resumo_html,
    }
