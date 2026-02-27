"""Matching engine — score client x opportunity."""
import json
import logging
import time

from django.conf import settings

from apps.ai_engine import prompts
from apps.clients.models import Client
from apps.opportunities.models import AISummary, Opportunity

from .models import Match

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _model = genai.GenerativeModel(
            settings.GEMINI_MODEL,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=16000,
            ),
        )
    return _model


def run_matching(opportunity: Opportunity, client: Client) -> Match:
    """Run AI-powered matching between a client and an opportunity."""

    # Build client profile
    client_profile = json.dumps({
        "razao_social": client.name,
        "cnpj": client.cnpj,
        "regioes": client.regions,
        "palavras_chave": client.keywords,
        "categorias": client.categories,
        "margem_minima_pct": str(client.min_margin_pct),
        "valor_maximo": str(client.max_value or "sem limite"),
        "alcance_logistico": client.logistics_reach,
        "restricoes": client.restrictions,
        "documentos_disponiveis": [
            {
                "tipo": doc.doc_type,
                "status": doc.status,
                "validade": str(doc.expires_at or ""),
            }
            for doc in client.documents.all()
        ],
    }, ensure_ascii=False, indent=2)

    # Build opportunity requirements
    opp_requirements = json.dumps({
        "objeto": opportunity.title,
        "descricao": opportunity.description,
        "modalidade": opportunity.get_modality_display(),
        "orgao": opportunity.entity_name,
        "uf": opportunity.entity_uf,
        "valor_estimado": str(opportunity.estimated_value or ""),
        "prazo": str(opportunity.deadline or ""),
        "srp": opportunity.is_srp,
    }, ensure_ascii=False, indent=2)

    # Get extracted checklist if available
    latest_analysis = opportunity.ai_summaries.filter(
        analysis_type=AISummary.AnalysisType.FULL
    ).first()
    checklist = "{}"
    if latest_analysis:
        checklist = json.dumps(
            latest_analysis.content.get("checklist_habilitacao", {}),
            ensure_ascii=False, indent=2,
        )

    user_prompt = prompts.MATCHING_USER.format(
        client_profile=client_profile,
        opportunity_requirements=opp_requirements,
        checklist=checklist,
    )

    prompt = f"{prompts.MATCHING_SYSTEM}\n\n---\n\n{user_prompt}"
    prompt += "\n\nIMPORTANTE: Responda APENAS com JSON válido, sem markdown ou texto adicional."

    model = _get_model()
    start = time.time()

    resp = model.generate_content(prompt)
    content = resp.text
    tokens = 0
    if resp.usage_metadata:
        tokens = (resp.usage_metadata.prompt_token_count or 0) + (resp.usage_metadata.candidates_token_count or 0)
    elapsed_ms = int((time.time() - start) * 1000)

    # Clean markdown fences
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = {"score": 0, "justificativa": "Erro ao processar resposta da IA"}

    # Upsert match
    match, _ = Match.objects.update_or_create(
        opportunity=opportunity,
        client=client,
        defaults={
            "score": min(100, max(0, data.get("score", 0))),
            "justification": data.get("justificativa", ""),
            "missing_docs": data.get("documentos_faltantes", []),
            "missing_capabilities": data.get("competencias_faltantes", []),
            "evidence": data.get("evidencias", []),
            "prompt_version": prompts.PROMPT_VERSION,
            "model_name": settings.GEMINI_MODEL,
        },
    )

    logger.info(
        "Match %s ↔ %s: score=%d (%d tokens, %dms)",
        client.name, opportunity.title[:50], match.score, tokens, elapsed_ms,
    )
    return match
