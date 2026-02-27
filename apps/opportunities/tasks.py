"""Celery tasks — document download and processing."""
import logging

import httpx
from celery import shared_task

from apps.core.storage import compute_file_hash

from .models import Opportunity, OpportunityDocument

logger = logging.getLogger(__name__)


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

    try:
        resp = httpx.get(doc.original_url, timeout=60, follow_redirects=True)
        resp.raise_for_status()

        content = resp.content
        file_hash = compute_file_hash(
            type("FakeFile", (), {"seek": lambda self, n: None, "read": lambda self, n=None: content})()
        )

        # Skip if already downloaded (idempotent by hash)
        if OpportunityDocument.objects.filter(file_hash=file_hash).exclude(pk=doc.pk).exists():
            doc.processing_status = OpportunityDocument.ProcessingStatus.DOWNLOADED
            doc.file_hash = file_hash
            doc.save(update_fields=["processing_status", "file_hash", "updated_at"])
            logger.info("Document %s already exists (hash match)", document_id)
            return

        # Determine filename
        filename = doc.file_name or doc.original_url.split("/")[-1] or f"{file_hash[:12]}.pdf"
        content_type = resp.headers.get("content-type", "")

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

        from apps.ai_engine.pipeline import (
            chunk_text,
            extract_text_from_docx,
            extract_text_from_pdf,
        )

        if "pdf" in mime or doc.file_name.lower().endswith(".pdf"):
            text, page_count, ocr_used = extract_text_from_pdf(file_content)
            doc.page_count = page_count
            doc.ocr_used = ocr_used
        elif "word" in mime or doc.file_name.lower().endswith(".docx"):
            text = extract_text_from_docx(file_content)
        else:
            text = file_content.decode("utf-8", errors="replace")

        doc.extracted_text = text
        doc.processing_status = OpportunityDocument.ProcessingStatus.INDEXED
        doc.save()

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

        # Generate embeddings
        from apps.ai_engine.embeddings import embed_chunks
        embed_chunks(list(doc.chunks.all()))

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
