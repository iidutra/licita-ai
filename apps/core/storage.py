"""MinIO/S3 storage helpers."""
import hashlib
import logging

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage

logger = logging.getLogger(__name__)


class DocumentStorage(S3Boto3Storage):
    """Storage for opportunity documents with hash-based paths."""

    location = "documents"
    file_overwrite = False


def compute_file_hash(file_obj) -> str:
    """SHA-256 hash of a file-like object. Resets seek position."""
    hasher = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(8192), b""):
        hasher.update(chunk)
    file_obj.seek(0)
    return hasher.hexdigest()


def document_upload_path(instance, filename: str) -> str:
    """Generate S3 path: documents/<source>/<year>/<hash_prefix>/<filename>."""
    hash_prefix = instance.file_hash[:8] if instance.file_hash else "unknown"
    year = instance.created_at.year if instance.created_at else "0000"
    source = getattr(instance, "source", "manual")
    return f"documents/{source}/{year}/{hash_prefix}/{filename}"
