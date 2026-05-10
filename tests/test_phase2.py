"""
Phase 2 Tests - Document Ingestion & RAG Pipeline

Before running these tests, generate sample files:
    python tests/create_samples.py
"""
import pytest
import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.document_parsers import parse_word, parse_excel, parse_pdf, parse_document
from backend.rag_pipeline import chunk_text, embed_texts, FAISSIndex

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")


# ── Helper ────────────────────────────────────────────────────────────────

def _skip_if_no_samples():
    """Skip test if sample files haven't been generated yet."""
    if not os.path.exists(SAMPLES_DIR):
        pytest.skip("Sample files not found. Run: python tests/create_samples.py")


# ── Document Parser Tests ─────────────────────────────────────────────────

class TestDocumentParsers:
    """Tests for the document parsing module."""

    def test_parse_word(self):
        _skip_if_no_samples()
        path = os.path.join(SAMPLES_DIR, "sample.docx")
        if not os.path.exists(path):
            pytest.skip("sample.docx not found")
        text = parse_word(path)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "RAGgent" in text or "sample" in text.lower()

    def test_parse_excel(self):
        _skip_if_no_samples()
        path = os.path.join(SAMPLES_DIR, "sample.xlsx")
        if not os.path.exists(path):
            pytest.skip("sample.xlsx not found")
        text = parse_excel(path)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "Laptop" in text or "Product" in text

    def test_parse_pdf(self):
        _skip_if_no_samples()
        path = os.path.join(SAMPLES_DIR, "sample.pdf")
        if not os.path.exists(path):
            pytest.skip("sample.pdf not found")
        text = parse_pdf(path)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_parse_document_auto_detect_docx(self):
        _skip_if_no_samples()
        path = os.path.join(SAMPLES_DIR, "sample.docx")
        if not os.path.exists(path):
            pytest.skip("sample.docx not found")
        text = parse_document(path)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_parse_document_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_document("file.txt")

    def test_parse_word_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_word("nonexistent.docx")

    def test_parse_word_wrong_extension(self):
        with pytest.raises(ValueError, match="Expected a .docx file"):
            parse_word("file.pdf")


# ── Chunking Tests ────────────────────────────────────────────────────────

class TestChunking:
    """Tests for the text chunking function."""

    def test_chunk_text_basic(self):
        text = "A" * 1024
        chunks = chunk_text(text, chunk_size=512, overlap=64)
        assert len(chunks) >= 2

    def test_chunk_text_small_input(self):
        text = "Hello world"
        chunks = chunk_text(text, chunk_size=512, overlap=64)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_chunk_text_empty(self):
        chunks = chunk_text("")
        assert chunks == []

    def test_chunk_text_overlap_works(self):
        text = "ABCDEFGHIJ"
        chunks = chunk_text(text, chunk_size=6, overlap=2)
        # First chunk: 0-6 = "ABCDEF", second: 4-10 = "EFGHIJ"
        assert len(chunks) >= 2
        # Verify overlap exists
        assert chunks[0][-2:] == chunks[1][:2]


# ── Embedding Tests ───────────────────────────────────────────────────────

class TestEmbedding:
    """Tests for the embedding function (uses actual model - may be slow first run)."""

    def test_embed_texts_returns_correct_shape(self):
        texts = ["Hello world", "How are you"]
        embeddings = embed_texts(texts)
        assert embeddings.shape[0] == 2
        assert embeddings.shape[1] > 0  # embedding dimension should be positive

    def test_embed_texts_dtype(self):
        texts = ["Test"]
        embeddings = embed_texts(texts)
        assert embeddings.dtype.name == "float32"


# ── FAISS Index Tests ─────────────────────────────────────────────────────

class TestFAISSIndex:
    """Tests for the FAISS index wrapper."""

    def test_build_and_search(self):
        chunks = [
            "Machine learning is a type of artificial intelligence.",
            "Python is a popular programming language.",
            "FAISS is a library for efficient similarity search.",
        ]
        idx = FAISSIndex()
        idx.build(chunks)

        results = idx.search("AI and machine learning", top_k=2)
        assert len(results) == 2
        # The closest result should be about machine learning
        assert "machine learning" in results[0][0].lower() or "artificial intelligence" in results[0][0].lower()

    def test_build_empty_raises(self):
        idx = FAISSIndex()
        with pytest.raises(ValueError, match="empty"):
            idx.build([])

    def test_search_empty_index(self):
        idx = FAISSIndex()
        results = idx.search("anything")
        assert results == []

    def test_save_and_load(self, tmp_path):
        chunks = ["Chunk one about dogs.", "Chunk two about cats."]
        idx = FAISSIndex()
        idx.build(chunks)

        # Save
        idx.save(str(tmp_path), name="test_index")

        # Load into a new instance
        idx2 = FAISSIndex()
        idx2.load(str(tmp_path), name="test_index")

        assert idx2.chunks == chunks
        assert idx2.index.ntotal == 2

        # Search should still work
        results = idx2.search("dogs", top_k=1)
        assert len(results) == 1
        assert "dogs" in results[0][0]
