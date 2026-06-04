"""Local RAG system using ChromaDB + sentence-transformers."""

import os
import hashlib
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions


class LaptopKnowledgeBase:
    """Ingest documents and retrieve context for agent decisions."""

    def __init__(self, chroma_path: str = "./data/chroma_db",
                 collection_name: str = "laptop_knowledge",
                 embedding_model: str = "all-MiniLM-L6-v2",
                 chunk_size: int = 512,
                 chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.client = chromadb.PersistentClient(path=chroma_path)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def ingest_file(self, file_path: str) -> int:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(file_path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        chunks = self._chunk(text)
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{file_path}:{i}".encode()).hexdigest()
            ids.append(doc_id)
            docs.append(chunk)
            metas.append({"source": str(p), "chunk": i})
        if ids:
            self.collection.upsert(ids=ids, documents=docs, metadatas=metas)
        return len(ids)

    def ingest_directory(self, directory: str,
                         extensions: list[str] | None = None) -> dict[str, int]:
        exts = set(extensions or [".txt", ".md", ".log", ".py", ".yaml", ".json"])
        results = {}
        for p in Path(directory).rglob("*"):
            if p.suffix.lower() in exts and p.is_file():
                try:
                    count = self.ingest_file(str(p))
                    results[str(p)] = count
                except Exception as e:
                    results[str(p)] = -1
        return results

    def query(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        results = self.collection.query(
            query_texts=[question],
            n_results=min(top_k, self.collection.count() or 1),
        )
        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append({
                "text": doc,
                "source": meta.get("source", ""),
                "chunk": meta.get("chunk", 0),
                "score": round(1 - dist, 4),
            })
        return sorted(hits, key=lambda x: x["score"], reverse=True)

    def count(self) -> int:
        return self.collection.count()

    def _chunk(self, text: str) -> list[str]:
        words = text.split()
        chunks, i = [], 0
        while i < len(words):
            chunk = " ".join(words[i: i + self.chunk_size])
            chunks.append(chunk)
            i += self.chunk_size - self.chunk_overlap
        return chunks
