"""
AI Pipeline — Document processing: PDF → text → chunks → embeddings.

Estratégia de OCR:
1. Tenta extrair texto com pdfplumber (nativo).
2. Se o texto extraído for muito curto (< 100 chars por página), assume PDF escaneado.
3. Aciona OCR com pytesseract via conversão PDF → imagem.
"""
import io
import logging
import re

import pdfplumber
import tiktoken
from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 800  # tokens
CHUNK_OVERLAP = 100  # tokens


def extract_text_from_pdf(file_content: bytes) -> tuple[str, int, bool]:
    """
    Extract text from PDF bytes.

    Returns: (text, page_count, ocr_used)
    """
    text_parts = []
    page_count = 0
    ocr_used = False

    try:
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
    except Exception:
        logger.exception("pdfplumber extraction failed")
        return "", 0, False

    full_text = "\n\n".join(text_parts)

    # Se o texto é muito escasso, tentar OCR
    avg_chars_per_page = len(full_text) / max(page_count, 1)
    if avg_chars_per_page < 100 and page_count > 0:
        logger.info("Low text density (%.0f chars/page), attempting OCR", avg_chars_per_page)
        ocr_text = _ocr_pdf(file_content)
        if len(ocr_text) > len(full_text):
            full_text = ocr_text
            ocr_used = True

    return full_text, page_count, ocr_used


def _ocr_pdf(file_content: bytes) -> str:
    """OCR fallback using pytesseract."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract

        images = convert_from_bytes(file_content, dpi=200)
        parts = []
        for img in images:
            text = pytesseract.image_to_string(img, lang=settings.TESSERACT_LANG)
            parts.append(text)
        return "\n\n".join(parts)
    except ImportError:
        logger.warning("pdf2image not available, OCR skipped")
        return ""
    except Exception:
        logger.exception("OCR failed")
        return ""


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split text into overlapping chunks by token count.

    Returns list of {"content": str, "token_count": int, "page_number": int|None}
    """
    enc = tiktoken.encoding_for_model("gpt-4o")
    tokens = enc.encode(text)

    chunks = []
    start = 0
    chunk_idx = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)

        # Estimate page number from text position
        text_position = len(enc.decode(tokens[:start]))
        page_breaks_before = text[:text_position].count("\n\n")
        estimated_page = max(1, page_breaks_before // 2 + 1)

        chunks.append({
            "content": chunk_text.strip(),
            "token_count": len(chunk_tokens),
            "page_number": estimated_page,
            "chunk_index": chunk_idx,
        })

        start = end - overlap if end < len(tokens) else end
        chunk_idx += 1

    return chunks


def extract_text_from_docx(file_content: bytes) -> str:
    """Extract text from a .docx file."""
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_content))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        logger.exception("DOCX extraction failed")
        return ""
