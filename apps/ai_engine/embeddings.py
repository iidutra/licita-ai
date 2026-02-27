"""Embedding generation and vector search using Gemini + pgvector."""
import logging

from django.conf import settings
from pgvector.django import CosineDistance

from apps.opportunities.models import DocumentChunk

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _client = genai
    return _client


def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for a text string."""
    client = _get_client()
    result = client.embed_content(
        model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
        content=text,
        task_type="retrieval_document",
    )
    return result["embedding"]


def embed_chunks(chunks: list[DocumentChunk]) -> int:
    """Generate and save embeddings for a list of chunks."""
    client = _get_client()
    texts = [c.content for c in chunks]

    batch_size = 100
    embedded_count = 0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_chunks = chunks[i : i + batch_size]

        result = client.embed_content(
            model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
            content=batch_texts,
            task_type="retrieval_document",
        )

        for chunk, emb in zip(batch_chunks, result["embedding"]):
            chunk.embedding = emb
            chunk.save(update_fields=["embedding", "updated_at"])
            embedded_count += 1

    logger.info("Embedded %d chunks", embedded_count)
    return embedded_count


def search_similar_chunks(
    query: str,
    opportunity_id: str | None = None,
    top_k: int = 10,
) -> list[DocumentChunk]:
    """Find the most relevant chunks for a query using cosine similarity."""
    client = _get_client()
    result = client.embed_content(
        model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
        content=query,
        task_type="retrieval_query",
    )
    query_embedding = result["embedding"]

    qs = DocumentChunk.objects.filter(embedding__isnull=False)
    if opportunity_id:
        qs = qs.filter(document__opportunity_id=opportunity_id)

    results = (
        qs.annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")[:top_k]
    )
    return list(results)
