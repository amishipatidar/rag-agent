"""
RAG Pipeline - Text chunking, FAISS embedding/indexing, and retrieval.
Uses sentence-transformers (all-MiniLM-L6-v2) for embeddings.
"""
import os
import numpy as np
from typing import List, Tuple, Optional


# ── Chunking ──────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> List[str]:
    """
    Split text into overlapping chunks by character count.

    Args:
        text: The full document text.
        chunk_size: Maximum characters per chunk.
        overlap: Number of overlapping characters between consecutive chunks.

    Returns:
        A list of text chunks.
    """
    if not text or not text.strip():
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap

    return chunks


# ── Embedding Model (lazy singleton) ──────────────────────────────────────

_embedding_model = None


def _get_embedding_model():
    """Lazy-load the sentence-transformer embedding model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Generate embeddings for a list of text strings.

    Args:
        texts: List of text strings to embed.

    Returns:
        A numpy array of shape (len(texts), embedding_dim).
    """
    model = _get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return embeddings.astype("float32")


# ── FAISS Index ───────────────────────────────────────────────────────────

class FAISSIndex:
    """
    Wrapper around a FAISS flat L2 index with associated text chunks.
    """

    def __init__(self):
        self.index = None
        self.chunks: List[str] = []

    def build(self, chunks: List[str]) -> None:
        """
        Embed and index a list of text chunks.

        Args:
            chunks: List of text strings to embed and index.
        """
        import faiss

        if not chunks:
            raise ValueError("Cannot build index from an empty chunk list.")

        self.chunks = chunks
        embeddings = embed_texts(chunks)
        dim = embeddings.shape[1]

        self.index = faiss.IndexFlatL2(dim)
        self.index.add(embeddings)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Search the FAISS index for the most relevant chunks.

        Args:
            query: The search query string.
            top_k: Number of top results to return.

        Returns:
            A list of (chunk_text, distance) tuples, sorted by relevance.
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        query_embedding = embed_texts([query])
        distances, indices = self.index.search(query_embedding, min(top_k, self.index.ntotal))

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(self.chunks):
                results.append((self.chunks[idx], float(dist)))

        return results

    def save(self, directory: str, name: str = "index") -> None:
        """
        Save the FAISS index and chunk metadata to disk.

        Args:
            directory: Directory to save into.
            name: Base name for the saved files.
        """
        import faiss
        import json

        os.makedirs(directory, exist_ok=True)
        faiss.write_index(self.index, os.path.join(directory, f"{name}.faiss"))

        with open(os.path.join(directory, f"{name}_chunks.json"), "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, ensure_ascii=False)

    def load(self, directory: str, name: str = "index") -> None:
        """
        Load a previously saved FAISS index and chunk metadata.

        Args:
            directory: Directory to load from.
            name: Base name of the saved files.
        """
        import faiss
        import json

        index_path = os.path.join(directory, f"{name}.faiss")
        chunks_path = os.path.join(directory, f"{name}_chunks.json")

        if not os.path.exists(index_path) or not os.path.exists(chunks_path):
            raise FileNotFoundError(f"Index files not found in: {directory}")

        self.index = faiss.read_index(index_path)

        with open(chunks_path, "r", encoding="utf-8") as f:
            self.chunks = json.load(f)


# ── Convenience Functions ─────────────────────────────────────────────────

def ingest_document(file_path: str, chunk_size: int = 512, overlap: int = 64):
    """
    Full pipeline: parse a document, chunk it, embed it, and return a FAISS index.

    Args:
        file_path: Path to the document (.docx, .xlsx, .pdf).
        chunk_size: Characters per chunk.
        overlap: Overlap between chunks.

    Returns:
        A tuple of (FAISSIndex ready for search, raw_text).
    """
    from backend.document_parsers import parse_document

    text = parse_document(file_path)
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    
    faiss_index = FAISSIndex()
    if chunks:
        faiss_index.build(chunks)
    return faiss_index, text


def search_faiss(faiss_index: FAISSIndex, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
    """
    Search a FAISS index for relevant chunks.

    Args:
        faiss_index: The FAISSIndex to search.
        query: User query string.
        top_k: Number of top results.

    Returns:
        List of (chunk_text, distance) tuples.
    """
    return faiss_index.search(query, top_k=top_k)
