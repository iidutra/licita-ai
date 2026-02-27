"""Shared utilities."""
import hashlib
import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalize text for deduplication: lowercase, strip accents, collapse spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def dedup_key(source: str, external_id: str) -> str:
    """Create deterministic dedup key: source + external ID."""
    return hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()


def object_hash(text: str) -> str:
    """Hash of normalized object description for fuzzy dedup."""
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
