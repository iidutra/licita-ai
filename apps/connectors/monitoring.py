"""Monitoring engine — detect and persist changes in PNCP procurements."""
import hashlib
import logging
from datetime import datetime

from django.utils import timezone

from apps.opportunities.models import Opportunity, OpportunityEvent

logger = logging.getLogger(__name__)


def event_dedup_hash(opp_id: str, event_type: str, new_value: str) -> str:
    """Deterministic SHA-256 hash for event idempotency."""
    raw = f"{opp_id}:{event_type}:{new_value}"
    return hashlib.sha256(raw.encode()).hexdigest()


def detect_changes(
    opportunity: Opportunity,
    fresh_data: dict,
    fresh_docs: list[dict],
    fresh_results: list[dict],
    fresh_atas: list[dict],
) -> list[dict]:
    """
    Compare fresh API data with stored state and return a list of event dicts.

    Each dict has: event_type, old_value, new_value, description, raw_data.
    """
    events = []
    old_raw = opportunity.raw_data or {}

    # 1. Status change (situacaoCompraId / situacaoCompraNome)
    old_status = str(old_raw.get("situacaoCompraId", ""))
    new_status = str(fresh_data.get("situacaoCompraId", ""))
    if new_status and old_status != new_status:
        old_name = old_raw.get("situacaoCompraNome", old_status)
        new_name = fresh_data.get("situacaoCompraNome", new_status)
        events.append({
            "event_type": OpportunityEvent.EventType.STATUS_CHANGE,
            "old_value": str(old_name),
            "new_value": str(new_name),
            "description": f"Status alterado de '{old_name}' para '{new_name}'",
            "raw_data": {
                "old_situacao_id": old_status,
                "new_situacao_id": new_status,
            },
        })

    # 2. Deadline change (dataEncerramentoProposta)
    old_deadline = old_raw.get("dataEncerramentoProposta", "")
    new_deadline = fresh_data.get("dataEncerramentoProposta", "")
    if new_deadline and old_deadline != new_deadline:
        events.append({
            "event_type": OpportunityEvent.EventType.DEADLINE_CHANGED,
            "old_value": str(old_deadline),
            "new_value": str(new_deadline),
            "description": f"Prazo alterado de '{old_deadline}' para '{new_deadline}'",
            "raw_data": {},
        })

    # 3. Value change (valorTotalHomologado)
    old_value = old_raw.get("valorTotalHomologado")
    new_value = fresh_data.get("valorTotalHomologado")
    if new_value is not None and old_value != new_value:
        events.append({
            "event_type": OpportunityEvent.EventType.VALUE_CHANGED,
            "old_value": str(old_value or ""),
            "new_value": str(new_value),
            "description": f"Valor homologado alterado de R$ {old_value or 'N/A'} para R$ {new_value}",
            "raw_data": {},
        })

    # 4. New documents (compare URLs with existing)
    existing_urls = set(
        opportunity.documents.values_list("original_url", flat=True)
    )
    for doc in fresh_docs:
        doc_url = doc.get("url", "")
        if doc_url and doc_url not in existing_urls:
            events.append({
                "event_type": OpportunityEvent.EventType.NEW_DOCUMENT,
                "old_value": "",
                "new_value": doc.get("file_name", doc_url),
                "description": f"Novo documento: {doc.get('file_name', '')} ({doc.get('doc_type', '')})",
                "raw_data": doc,
            })

    # 5. Results published
    if fresh_results:
        old_results_count = len(old_raw.get("_monitored_results", []))
        if len(fresh_results) > old_results_count:
            new_results = fresh_results[old_results_count:]
            for result in new_results:
                item_num = result.get("_itemNumero", "?")
                fornecedor = result.get("nomeRazaoSocialFornecedor", "")
                valor = result.get("valorTotalHomologado", "")
                events.append({
                    "event_type": OpportunityEvent.EventType.RESULT_PUBLISHED,
                    "old_value": "",
                    "new_value": f"Item {item_num}: {fornecedor} - R$ {valor}",
                    "description": f"Resultado publicado para item {item_num}: {fornecedor}",
                    "raw_data": result,
                })

    # 6. Atas published
    if fresh_atas:
        old_atas_count = len(old_raw.get("_monitored_atas", []))
        if len(fresh_atas) > old_atas_count:
            new_atas = fresh_atas[old_atas_count:]
            for ata in new_atas:
                numero = ata.get("numeroAta", "")
                events.append({
                    "event_type": OpportunityEvent.EventType.ATA_PUBLISHED,
                    "old_value": "",
                    "new_value": f"Ata {numero}",
                    "description": f"Nova ata de registro de preço publicada: {numero}",
                    "raw_data": ata,
                })

    return events


def persist_events(
    opportunity: Opportunity, event_dicts: list[dict]
) -> list[OpportunityEvent]:
    """
    Persist events using get_or_create for idempotency (dedup_hash).

    Returns list of newly created events only.
    """
    created_events = []
    for ev in event_dicts:
        d_hash = event_dedup_hash(
            str(opportunity.pk), ev["event_type"], ev["new_value"]
        )
        obj, created = OpportunityEvent.objects.get_or_create(
            dedup_hash=d_hash,
            defaults={
                "opportunity": opportunity,
                "event_type": ev["event_type"],
                "old_value": ev.get("old_value", ""),
                "new_value": ev.get("new_value", ""),
                "description": ev.get("description", ""),
                "raw_data": ev.get("raw_data", {}),
            },
        )
        if created:
            created_events.append(obj)
            logger.info(
                "New event: %s for %s — %s",
                ev["event_type"], opportunity.external_id, ev["description"],
            )
    return created_events


def update_opportunity_from_fresh(
    opportunity: Opportunity,
    fresh_data: dict,
    fresh_results: list[dict] | None = None,
    fresh_atas: list[dict] | None = None,
) -> None:
    """Update opportunity raw_data and fields from fresh API data."""
    update_fields = ["raw_data", "last_monitored_at", "updated_at"]

    # Preserve monitoring metadata in raw_data
    fresh_data["_monitored_results"] = fresh_results or []
    fresh_data["_monitored_atas"] = fresh_atas or []
    opportunity.raw_data = fresh_data
    opportunity.last_monitored_at = timezone.now()

    # Update deadline if changed
    new_deadline_str = fresh_data.get("dataEncerramentoProposta")
    if new_deadline_str:
        try:
            new_deadline = datetime.fromisoformat(
                new_deadline_str.replace("Z", "+00:00")
            )
            if opportunity.deadline != new_deadline:
                opportunity.deadline = new_deadline
                update_fields.append("deadline")
        except (ValueError, AttributeError):
            pass

    # Update awarded_value if changed
    new_awarded = fresh_data.get("valorTotalHomologado")
    if new_awarded is not None and opportunity.awarded_value != new_awarded:
        opportunity.awarded_value = new_awarded
        update_fields.append("awarded_value")

    opportunity.save(update_fields=update_fields)
