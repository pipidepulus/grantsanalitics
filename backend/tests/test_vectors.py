"""
Unit tests for vector_store utilities.
Tests safe_vector sanitization, chunking, and retrieval logic.
"""

import json
import uuid
from unittest.mock import patch, MagicMock

from app.services.vector_store import safe_vector, _chunk_document, OllamaEmbeddingFn


class TestSafeVector:
    def test_nan_replaced_with_zero(self):
        vec = [1.0, float('nan'), 3.0]
        result = safe_vector(vec)
        assert result == [1.0, 0.0, 3.0]

    def test_inf_replaced_with_zero(self):
        vec = [1.0, float('inf'), 3.0]
        result = safe_vector(vec)
        assert result == [1.0, 0.0, 3.0]

    def test_neg_inf_replaced_with_zero(self):
        vec = [1.0, float('-inf'), 3.0]
        result = safe_vector(vec)
        assert result == [1.0, 0.0, 3.0]

    def test_valid_values_unchanged(self):
        vec = [0.1, 0.2, -0.5, 1.0, 0.999]
        result = safe_vector(vec)
        assert result == [0.1, 0.2, -0.5, 1.0, 0.999]

    def test_empty_list(self):
        result = safe_vector([])
        assert result == []

    def test_all_nan(self):
        vec = [float('nan')] * 5
        result = safe_vector(vec)
        assert result == [0.0] * 5

    def test_mixed_nan_and_inf(self):
        vec = [float('nan'), float('-inf'), 0.5, float('inf')]
        result = safe_vector(vec)
        assert result == [0.0, 0.0, 0.5, 0.0]


class TestChunkDocument:
    def test_short_text_returns_as_single_chunk(self):
        text = "Hola mundo"
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert len(result) == 1
        assert result[0] == text

    def test_long_text_splits_into_chunks(self):
        # 2400 chars → 3 chunks of ~800 with 200 overlap
        text = "a" * 2400
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert len(result) == 3
        for chunk in result[1:]:
            # Overlap of 200 chars between chunks
            pass

    def test_exact_chunk_size_boundary(self):
        # Exactly 801 chars → should split
        text = "a" * 801
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert len(result) == 1

    def test_exactly_chunk_size_returns_single(self):
        text = "a" * 800
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert len(result) == 1

    def test_double_chunk_size_with_overlap(self):
        text = "a" * 1601  # Just over 800 + 800 - 200 overlap
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert len(result) == 2

    def test_utf8_roundtrip(self):
        text = "Hola 🌍 mundo!"
        result = _chunk_document(text.encode("utf-8"), "test.txt")
        assert result[0] == text

    def test_latin1_decode_fallback(self):
        text = "Héllo wörld"
        # Encode as latin-1, simulate UnicodeDecodeError
        latin_bytes = text.encode("latin-1")
        # Should fall back to latin-1 with errors="replace"
        result = _chunk_document(latin_bytes, "test.txt")
        assert len(result) == 1


class TestOllamaEmbeddingFn:
    def test_init_uses_default_model(self):
        fn = OllamaEmbeddingFn()
        assert fn.model == "nomic-embed-text"

    def test_init_uses_custom_model(self):
        fn = OllamaEmbeddingFn(model="my-custom-model")
        assert fn.model == "my-custom-model"

    @patch("app.services.vector_store.ollama")
    def test_embed_calls_ollama(self, mock_ollama):
        mock_ollama.embeddings.return_value = {
            "embedding": [0.1, 0.2, 0.3]
        }
        fn = OllamaEmbeddingFn()
        result = fn.embed("test")
        assert result == [0.1, 0.2, 0.3]
        mock_ollama.embeddings.assert_called_once()

    @patch("app.services.vector_store.ollama")
    def test_embed_sanitizes_nan(self, mock_ollama):
        mock_ollama.embeddings.return_value = {
            "embedding": [0.1, float('nan'), 0.3]
        }
        fn = OllamaEmbeddingFn()
        result = fn.embed("test")
        assert result == [0.1, 0.0, 0.3]

    @patch("app.services.vector_store.ollama")
    def test_embed_batch_calls_embed_per_text(self, mock_ollama):
        mock_ollama.embeddings.side_effect = [
            {"embedding": [0.1] * 768},
            {"embedding": [0.2] * 768},
        ]
        fn = OllamaEmbeddingFn()
        texts = ["texto1", "texto2"]
        result = fn.embed_batch(texts)
        assert len(result) == 2
        assert len(result[0]) == 768
        assert len(result[1]) == 768
        assert mock_ollama.embeddings.call_count == 2


class TestSearchKnowledgeBase:
    @patch("app.services.vector_store._ensure_kb")
    def test_empty_collection_returns_empty(self, mock_ensure_kb):
        from app.services.vector_store import search_knowledge_base
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_ensure_kb.return_value = mock_col

        result = search_knowledge_base("test query")
        assert result == []

    @patch("app.services.vector_store._ensure_kb")
    @patch("app.services.vector_store.OllamaEmbeddingFn")
    def test_returns_formatted_results(self, mock_fn_cls, mock_ensure_kb):
        from app.services.vector_store import search_knowledge_base

        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "ids": [["id1", "id2"]],
            "documents": [["doc1 content", "doc2 content"]],
            "metadatas": [[{"filename": "file1.txt"}], [{"filename": "file2.txt"}]],
            "distances": [[0.1, 0.2]],
        }
        mock_ensure_kb.return_value = mock_col

        mock_fn = MagicMock()
        mock_fn_cls.return_value = mock_fn
        mock_fn.embed.return_value = [0.0] * 768

        result = search_knowledge_base("test query", max_results=10)
        assert len(result) == 2
        assert result[0]["content"] == "doc1 content"
        assert result[0]["score"] == 0.1
        assert result[0]["filename"] == "file1.txt"


class TestRetrieveProjectContext:
    @patch("app.services.vector_store.search_projects_store")
    def test_no_results_returns_empty(self, mock_search):
        from app.services.retrieval import retrieve_project_context
        mock_search.return_value = []
        result = retrieve_project_context(uuid.uuid4(), "query")
        assert result == ""

    @patch("app.services.vector_store.search_projects_store")
    def test_escapes_html_content(self, mock_search):
        from app.services.retrieval import retrieve_project_context
        mock_search.return_value = [{
            "content": '<script>hack()</script>',
            "filename": "test.md",
            "score": 0.5,
            "metadata": {"filename": "test.md"},
        }]

        result = retrieve_project_context(uuid.uuid4(), "query")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    @patch("app.services.vector_store.search_projects_store")
    def test_formats_chunk_blocks(self, mock_search):
        from app.services.retrieval import retrieve_project_context
        mock_search.return_value = [{
            "content": "Content here",
            "filename": "doc.md",
            "score": 0.3,
            "metadata": {"filename": "doc.md"},
        }]

        result = retrieve_project_context(uuid.uuid4(), "query")
        assert "<project_documents>" in result
        assert "</project_documents>" in result
        assert "doc.md" in result
        assert "Content here" in result
