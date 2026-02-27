"""Normalize and persist opportunities from connectors."""
import logging
from datetime import datetime

import zoneinfo

from django.utils.dateparse import parse_datetime

from apps.core.utils import dedup_key, object_hash
from apps.opportunities.models import Opportunity, OpportunityDocument, OpportunityItem

from .base import NormalizedOpportunity

logger = logging.getLogger(__name__)


def _s(val, max_len: int = 0) -> str:
    """Safely coerce to string, truncating if max_len > 0."""
    s = val if isinstance(val, str) else (str(val) if val is not None else "")
    return s[:max_len] if max_len else s


_UTC = zoneinfo.ZoneInfo("UTC")


def _safe_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_UTC)
        return value
    if isinstance(value, str):
        dt = parse_datetime(value)
        if dt and dt.tzinfo is None:
            return dt.replace(tzinfo=_UTC)
        return dt
    return None


def persist_opportunity(norm: NormalizedOpportunity) -> tuple[Opportunity, bool]:
    """
    Persist a normalized opportunity with deduplication.

    Returns (opportunity, created).
    Idempotent: if dedup_hash exists, skips.
    """
    d_hash = dedup_key(norm.source, norm.external_id)
    o_hash = object_hash(norm.title or "")

    existing = Opportunity.objects.filter(dedup_hash=d_hash).first()
    if existing:
        return existing, False

    # Cross-source dedup check: same object from different source
    cross = Opportunity.objects.filter(object_hash=o_hash).first()
    if cross:
        logger.info(
            "Cross-source duplicate detected: %s ↔ %s",
            norm.external_id, cross.external_id,
        )

    opp = Opportunity.objects.create(
        source=norm.source,
        external_id=_s(norm.external_id, 200),
        dedup_hash=d_hash,
        object_hash=o_hash,
        title=_s(norm.title),
        description=_s(norm.description),
        modality=_s(norm.modality, 30) or "other",
        number=_s(norm.number, 100),
        process_number=_s(norm.process_number, 100),
        entity_cnpj=_s(norm.entity_cnpj, 18),
        entity_name=_s(norm.entity_name, 400),
        entity_uf=_s(norm.entity_uf, 2),
        entity_city=_s(norm.entity_city, 200),
        published_at=_safe_datetime(norm.published_at),
        proposals_open_at=_safe_datetime(norm.proposals_open_at),
        proposals_close_at=_safe_datetime(norm.proposals_close_at),
        deadline=_safe_datetime(norm.deadline),
        estimated_value=norm.estimated_value,
        awarded_value=norm.awarded_value,
        is_srp=bool(norm.is_srp),
        link=_s(norm.link, 2000),
        raw_data=norm.raw_data or {},
    )

    # Persist items
    for item_data in norm.items:
        try:
            OpportunityItem.objects.create(opportunity=opp, **item_data)
        except Exception:
            logger.warning("Failed to persist item for %s", norm.external_id)

    # Persist document references
    for doc_data in norm.document_urls:
        try:
            OpportunityDocument.objects.create(
                opportunity=opp,
                original_url=doc_data.get("url", ""),
                file_name=_s(doc_data.get("file_name"), 500),
                doc_type=_s(doc_data.get("doc_type"), 100),
            )
        except Exception:
            logger.warning("Failed to persist document for %s", norm.external_id)

    logger.debug("Persisted opportunity: %s [%s]", opp.external_id, opp.source)
    return opp, True
