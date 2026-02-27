"""RAG — Retrieval-Augmented Generation for opportunity analysis."""
import json
import logging
import time

from django.conf import settings

from apps.opportunities.models import AISummary, ExtractedRequirement, Opportunity

from . import prompts
from .embeddings import search_similar_chunks

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


def _call_llm(system: str, user: str, response_format: str = "json_object") -> tuple[dict, int]:
    """Call Gemini LLM and return (parsed_json, tokens_used)."""
    model = _get_model()

    prompt = f"{system}\n\n---\n\n{user}"
    if response_format == "json_object":
        prompt += "\n\nIMPORTANTE: Responda APENAS com JSON válido, sem markdown ou texto adicional."

    resp = model.generate_content(prompt)
    content = resp.text

    tokens = 0
    if resp.usage_metadata:
        tokens = (resp.usage_metadata.prompt_token_count or 0) + (resp.usage_metadata.candidates_token_count or 0)

    if response_format == "json_object":
        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = {"raw_response": content}
            logger.warning("LLM response is not valid JSON: %s", content[:200])
    else:
        data = {"text": content}

    return data, tokens


def run_extraction(opportunity: Opportunity) -> AISummary:
    """Run full extraction: checklist + risks + fields."""
    api_metadata = json.dumps({
        "objeto": opportunity.title,
        "descricao": opportunity.description,
        "modalidade": opportunity.get_modality_display(),
        "orgao": opportunity.entity_name,
        "cnpj_orgao": opportunity.entity_cnpj,
        "uf": opportunity.entity_uf,
        "valor_estimado": str(opportunity.estimated_value or ""),
        "data_abertura": str(opportunity.proposals_open_at or ""),
        "data_encerramento": str(opportunity.proposals_close_at or ""),
        "srp": opportunity.is_srp,
    }, ensure_ascii=False, indent=2)

    # RAG: retrieve relevant chunks
    chunks = search_similar_chunks(
        query=opportunity.title,
        opportunity_id=str(opportunity.pk),
        top_k=15,
    )
    chunks_text = "\n\n---\n\n".join(
        f"[Documento: {c.document.file_name}, Página: {c.page_number}]\n{c.content}"
        for c in chunks
    )

    if not chunks_text:
        chunks_text = "(Nenhum documento indexado ainda. Análise baseada apenas nos metadados da API.)"

    user_prompt = prompts.EXTRACTION_USER.format(
        api_metadata=api_metadata,
        document_chunks=chunks_text,
    )

    start = time.time()
    data, tokens = _call_llm(prompts.EXTRACTION_SYSTEM, user_prompt)
    elapsed_ms = int((time.time() - start) * 1000)

    # Persist extracted requirements
    _persist_requirements(opportunity, data)

    summary = AISummary.objects.create(
        opportunity=opportunity,
        analysis_type=AISummary.AnalysisType.FULL,
        content=data,
        prompt_version=prompts.PROMPT_VERSION,
        model_name=settings.GEMINI_MODEL,
        tokens_used=tokens,
        processing_time_ms=elapsed_ms,
    )

    logger.info(
        "Extraction complete for %s: %d tokens, %dms",
        opportunity.pk, tokens, elapsed_ms,
    )
    return summary


def run_summary(opportunity: Opportunity) -> AISummary:
    """Generate executive summary."""
    api_metadata = json.dumps({
        "objeto": opportunity.title,
        "orgao": opportunity.entity_name,
        "uf": opportunity.entity_uf,
        "modalidade": opportunity.get_modality_display(),
        "valor_estimado": str(opportunity.estimated_value or ""),
        "prazo": str(opportunity.deadline or ""),
    }, ensure_ascii=False, indent=2)

    reqs = list(opportunity.requirements.values("category", "requirement"))
    latest_analysis = opportunity.ai_summaries.filter(
        analysis_type=AISummary.AnalysisType.FULL
    ).first()

    risks = latest_analysis.content.get("riscos", []) if latest_analysis else []

    user_prompt = prompts.SUMMARY_USER.format(
        api_metadata=api_metadata,
        requirements=json.dumps(reqs, ensure_ascii=False, default=str),
        risks=json.dumps(risks, ensure_ascii=False, default=str),
    )

    start = time.time()
    data, tokens = _call_llm(
        prompts.SUMMARY_SYSTEM, user_prompt, response_format="text"
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = AISummary.objects.create(
        opportunity=opportunity,
        analysis_type=AISummary.AnalysisType.EXECUTIVE_SUMMARY,
        content=data,
        prompt_version=prompts.PROMPT_VERSION,
        model_name=settings.GEMINI_MODEL,
        tokens_used=tokens,
        processing_time_ms=elapsed_ms,
    )
    return summary


def _persist_requirements(opportunity: Opportunity, data: dict):
    """Save extracted requirements as individual records."""
    opportunity.requirements.all().delete()

    checklist = data.get("checklist_habilitacao", {})
    category_map = {
        "fiscal": ExtractedRequirement.Category.FISCAL,
        "juridica": ExtractedRequirement.Category.JURIDICA,
        "tecnica": ExtractedRequirement.Category.TECNICA,
        "economica": ExtractedRequirement.Category.ECONOMICA,
    }

    for cat_key, cat_value in category_map.items():
        items = checklist.get(cat_key, [])
        for item in items:
            ExtractedRequirement.objects.create(
                opportunity=opportunity,
                category=cat_value,
                requirement=item.get("requisito", str(item)),
                evidence=item.get("evidencia", {}),
                is_mandatory=True,
            )
