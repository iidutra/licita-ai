"""Celery tasks — document download and processing."""
import hashlib
import io
import logging
import zipfile

import httpx
from celery import shared_task

from .models import Opportunity, OpportunityDocument

logger = logging.getLogger(__name__)


def _extract_text_from_zip(zip_content: bytes) -> tuple[str, int, bool]:
    """Extract text from PDFs/DOCXs inside a ZIP file."""
    from apps.ai_engine.pipeline import extract_text_from_docx, extract_text_from_pdf

    texts = []
    total_pages = 0
    ocr_used = False

    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            for name in sorted(zf.namelist()):
                lower = name.lower()
                if lower.endswith("/") or lower.startswith("__MACOSX"):
                    continue
                try:
                    data = zf.read(name)
                except Exception:
                    continue

                if lower.endswith(".pdf"):
                    text, pages, ocr = extract_text_from_pdf(data)
                    if text.strip():
                        texts.append(f"=== {name} ({pages} páginas) ===\n{text}")
                        total_pages += pages
                        ocr_used = ocr_used or ocr
                elif lower.endswith(".docx"):
                    text = extract_text_from_docx(data)
                    if text.strip():
                        texts.append(f"=== {name} ===\n{text}")
    except zipfile.BadZipFile:
        logger.warning("Invalid ZIP file")
        return "", 0, False

    return "\n\n".join(texts), total_pages, ocr_used


@shared_task(bind=True, queue="documents", max_retries=3, default_retry_delay=60)
def download_opportunity_documents(self, opportunity_id: str):
    """Download all pending documents for an opportunity."""
    try:
        opp = Opportunity.objects.get(pk=opportunity_id)
    except Opportunity.DoesNotExist:
        logger.error("Opportunity %s not found", opportunity_id)
        return

    pending_docs = opp.documents.filter(
        processing_status=OpportunityDocument.ProcessingStatus.PENDING
    )

    for doc in pending_docs:
        download_single_document.delay(str(doc.pk))


@shared_task(bind=True, queue="documents", max_retries=3, default_retry_delay=60)
def download_single_document(self, document_id: str):
    """Download a single document and compute its hash."""
    try:
        doc = OpportunityDocument.objects.get(pk=document_id)
    except OpportunityDocument.DoesNotExist:
        logger.error("Document %s not found", document_id)
        return

    if not doc.original_url:
        doc.processing_status = OpportunityDocument.ProcessingStatus.FAILED
        doc.error_message = "No URL"
        doc.save(update_fields=["processing_status", "error_message", "updated_at"])
        return

    doc.processing_status = OpportunityDocument.ProcessingStatus.DOWNLOADING
    doc.save(update_fields=["processing_status", "updated_at"])

    max_file_size = 200 * 1024 * 1024  # 200 MB

    try:
        with httpx.stream("GET", doc.original_url, timeout=60, follow_redirects=True) as resp:
            resp.raise_for_status()

            chunks = []
            total = 0
            content_type = resp.headers.get("content-type", "")
            for chunk in resp.iter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > max_file_size:
                    raise ValueError(f"File exceeds {max_file_size // (1024*1024)} MB limit")
                chunks.append(chunk)

        content = b"".join(chunks)
        file_hash = hashlib.sha256(content).hexdigest()

        # Dedup by hash: if another doc already has this content, copy its file
        # reference instead of saving a new one, but still proceed to extraction.
        existing = (
            OpportunityDocument.objects
            .filter(file_hash=file_hash)
            .exclude(pk=doc.pk)
            .exclude(file="")
            .first()
        )
        if existing and existing.file:
            doc.file = existing.file
            doc.file_hash = file_hash
            doc.file_size = existing.file_size
            doc.mime_type = existing.mime_type or content_type.split(";")[0].strip()
            doc.processing_status = OpportunityDocument.ProcessingStatus.DOWNLOADED
            doc.save(update_fields=[
                "file", "file_hash", "file_size", "mime_type",
                "processing_status", "updated_at",
            ])
            logger.info("Document %s deduped from %s (hash match)", document_id, existing.pk)
            extract_document_text.delay(str(doc.pk))
            return

        # Determine filename
        filename = doc.file_name or doc.original_url.split("/")[-1] or f"{file_hash[:12]}.pdf"

        from django.core.files.base import ContentFile
        doc.file.save(filename, ContentFile(content), save=False)
        doc.file_hash = file_hash
        doc.file_size = len(content)
        doc.mime_type = content_type.split(";")[0].strip()
        doc.processing_status = OpportunityDocument.ProcessingStatus.DOWNLOADED
        doc.save()

        logger.info("Downloaded: %s (%d bytes)", filename, len(content))

        # Enqueue text extraction
        extract_document_text.delay(str(doc.pk))

    except Exception as exc:
        doc.processing_status = OpportunityDocument.ProcessingStatus.FAILED
        doc.error_message = str(exc)[:500]
        doc.save(update_fields=["processing_status", "error_message", "updated_at"])
        logger.exception("Download failed for %s", doc.original_url)
        raise self.retry(exc=exc)


@shared_task(bind=True, queue="documents", max_retries=2, default_retry_delay=30)
def extract_document_text(self, document_id: str):
    """Extract text from a downloaded document and create chunks + embeddings."""
    try:
        doc = OpportunityDocument.objects.get(pk=document_id)
    except OpportunityDocument.DoesNotExist:
        return

    if not doc.file:
        return

    doc.processing_status = OpportunityDocument.ProcessingStatus.EXTRACTING
    doc.save(update_fields=["processing_status", "updated_at"])

    try:
        file_content = doc.file.read()
        mime = doc.mime_type.lower()
        fname = (doc.file_name or "").lower()

        from apps.ai_engine.pipeline import (
            chunk_text,
            extract_text_from_docx,
            extract_text_from_pdf,
        )

        # Handle ZIP files: extract PDFs inside and concatenate text
        is_zip = (
            "zip" in mime
            or fname.endswith(".zip")
            or file_content[:4] == b"PK\x03\x04"
        )
        if is_zip:
            text, page_count, ocr_used = _extract_text_from_zip(file_content)
            doc.page_count = page_count
            doc.ocr_used = ocr_used
        elif "pdf" in mime or fname.endswith(".pdf"):
            text, page_count, ocr_used = extract_text_from_pdf(file_content)
            doc.page_count = page_count
            doc.ocr_used = ocr_used
        elif "word" in mime or fname.endswith(".docx"):
            text = extract_text_from_docx(file_content)
        else:
            text = file_content.decode("utf-8", errors="replace")

        # PostgreSQL TEXT fields cannot contain NUL bytes
        text = text.replace("\x00", "")
        doc.extracted_text = text
        doc.file_name = (doc.file_name or "").replace("\x00", "")
        doc.processing_status = OpportunityDocument.ProcessingStatus.INDEXED
        doc.save(update_fields=[
            "extracted_text", "file_name", "page_count", "ocr_used",
            "processing_status", "updated_at",
        ])

        # Create chunks
        from apps.opportunities.models import DocumentChunk

        doc.chunks.all().delete()  # Idempotent reprocessing
        chunks_data = chunk_text(text)

        chunk_objs = []
        for cd in chunks_data:
            chunk_objs.append(DocumentChunk(
                document=doc,
                chunk_index=cd["chunk_index"],
                content=cd["content"],
                page_number=cd["page_number"],
                token_count=cd["token_count"],
            ))
        DocumentChunk.objects.bulk_create(chunk_objs)

        # Generate embeddings (non-fatal — AI can still use chunks without embeddings)
        try:
            from apps.ai_engine.embeddings import embed_chunks
            embed_chunks(list(doc.chunks.all()))
        except Exception:
            logger.warning("Embedding failed for %s, chunks saved without vectors", doc.file_name, exc_info=True)

        logger.info("Indexed document %s: %d chunks", doc.file_name, len(chunk_objs))

    except Exception as exc:
        doc.processing_status = OpportunityDocument.ProcessingStatus.FAILED
        doc.error_message = str(exc)[:500]
        doc.save(update_fields=["processing_status", "error_message", "updated_at"])
        logger.exception("Text extraction failed for %s", document_id)
        raise self.retry(exc=exc)


@shared_task(queue="documents")
def download_pending_documents():
    """Scan for documents with pending status and enqueue download."""
    pending = OpportunityDocument.objects.filter(
        processing_status=OpportunityDocument.ProcessingStatus.PENDING,
        original_url__gt="",
    ).values_list("pk", flat=True)[:200]

    for doc_id in pending:
        download_single_document.delay(str(doc_id))

    return {"enqueued": len(pending)}
