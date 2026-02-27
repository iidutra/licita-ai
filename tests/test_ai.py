"""Tests for AI pipeline — unit tests with mocked LLM calls."""
import json
from unittest.mock import MagicMock, patch

import pytest

from apps.ai_engine.pipeline import chunk_text


class TestChunking:
    def test_chunk_text_basic(self):
        text = "Hello world. " * 500  # ~1000 tokens
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        assert all(c["token_count"] <= 100 for c in chunks)

    def test_chunk_text_small(self):
        text = "Short text."
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) == 1

    def test_chunk_text_preserves_content(self):
        text = "The quick brown fox jumps over the lazy dog."
        chunks = chunk_text(text, chunk_size=1000, overlap=0)
        assert len(chunks) == 1
        assert "quick brown fox" in chunks[0]["content"]


class TestAIRAG:
    @patch("apps.ai_engine.rag._get_client")
    @patch("apps.ai_engine.embeddings.search_similar_chunks")
    def test_run_extraction(self, mock_search, mock_client, sample_opportunity):
        """Test extraction with mocked LLM."""
        mock_search.return_value = []

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "resumo": "Aquisição de software",
                "checklist_habilitacao": {
                    "fiscal": [{"requisito": "CND Federal", "evidencia": {"fonte": "api", "trecho": "...", "pagina": None, "confianca": 0.8}}],
                    "juridica": [],
                    "tecnica": [],
                    "economica": [],
                },
                "riscos": [],
                "campos_extraidos": {},
            })))
        ]
        mock_response.usage = MagicMock(total_tokens=500)

        llm_instance = MagicMock()
        llm_instance.chat.completions.create.return_value = mock_response
        mock_client.return_value = llm_instance

        from apps.ai_engine.rag import run_extraction
        summary = run_extraction(sample_opportunity)

        assert summary.analysis_type == "full"
        assert summary.tokens_used == 500
        assert sample_opportunity.requirements.count() == 1
