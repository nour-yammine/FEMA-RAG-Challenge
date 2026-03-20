"""
retrieval/retriever.py — Query the ChromaDB vector store and return
ranked chunks with metadata for the chat API.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    CHROMA_DB_PATH,
    CHROMA_COLLECTION,
    CROSS_REF_MAX_EXTRA_QUERIES,
    EMBEDDING_MODEL,
    DEFAULT_TOP_K,
)
from retrieval.query_enrichment import expand_query_for_embedding, extract_followup_queries


class Retriever:
    """
    Singleton-style retriever: loads the embedding model and ChromaDB
    collection once and reuses them across requests.
    """

    def __init__(self):
        self._embedder: Optional[SentenceTransformer] = None
        self._collection = None
        self._load_lock = threading.Lock()

    def _load(self):
        # Thread-safe lazy init (avoids intermittent NoneType count errors
        # when concurrent requests hit /health or /ingestion-status on startup).
        if self._embedder is not None and self._collection is not None:
            return

        with self._load_lock:
            if self._embedder is not None and self._collection is not None:
                return

            print(f"[retriever] Loading embedding model: {EMBEDDING_MODEL}")
            embedder = SentenceTransformer(EMBEDDING_MODEL)
            client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
            collection = client.get_or_create_collection(
                name=CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )

            # Assign only after both objects are ready.
            self._embedder = embedder
            self._collection = collection
            print(f"[retriever] Collection '{CHROMA_COLLECTION}' — {self._collection.count()} chunks")

    def _query_once(
        self,
        question: str,
        top_k: int,
        where: Optional[dict] = None,
    ) -> List[dict]:
        """
        Embed `question` and return ranked chunks from ChromaDB.

        Returns a list of chunk dicts (with similarity score conversion):
        {
            chunk_id, text, score, source_document, document_label,
            page_number, section, chunk_index, chunk_strategy
        }
        Score is the cosine similarity (0–1, higher = more similar).
        ChromaDB returns distances; we convert: similarity = 1 - distance.
        """
        self._load()

        # Embed expanded query (acronym → long form) for better lexical/semantic match
        embedding_text = expand_query_for_embedding(question)
        query_embedding = self._embedder.encode([embedding_text])[0].tolist()

        # Query ChromaDB
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        if not results["ids"] or not results["ids"][0]:
            return chunks

        for             chunk_id, text, meta, distance in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance is in [0, 2]; convert to similarity [0, 1]
            similarity = round(1 - (distance / 2), 4)
            sec = meta.get("section", "") or ""
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "text": text,
                    "score": similarity,
                    "source_document": meta.get("source_document", "Unknown"),
                    "document_label": meta.get("document_label", "Unknown"),
                    "page_number": meta.get("page_number", 0),
                    "section": sec,
                    "section_path": meta.get("section_path") or sec,
                    "chunk_index": meta.get("chunk_index", 0),
                    "chunk_strategy": meta.get("chunk_strategy", ""),
                }
            )

        # Sort by score descending (ChromaDB may not guarantee order with where filter)
        chunks.sort(key=lambda c: c["score"], reverse=True)
        return chunks

    def _enrich_with_cross_refs(
        self,
        question: str,
        chunks: List[dict],
        top_k: int,
        where: Optional[dict],
    ) -> List[dict]:
        """
        Second-stage retrieval: short queries mined from 'see Section …' / form references
        in the question and top chunks, merged by max score per chunk_id.
        """
        if not chunks or CROSS_REF_MAX_EXTRA_QUERIES <= 0:
            return chunks[:top_k]

        merged: Dict[str, dict] = {c["chunk_id"]: c for c in chunks}
        snippets = [c["text"] for c in chunks[:4]]
        extra_qs = extract_followup_queries(
            question,
            snippets,
            CROSS_REF_MAX_EXTRA_QUERIES,
        )
        for fq in extra_qs:
            for c in self._query_once(
                fq,
                top_k=max(top_k, 6),
                where=where,
            ):
                cid = c["chunk_id"]
                prev = merged.get(cid)
                if prev is None or c["score"] > prev["score"]:
                    merged[cid] = c

        out = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    def query(
        self,
        question: str,
        top_k: int = DEFAULT_TOP_K,
        filter_document: Optional[str] = None,
        filter_document_label: Optional[str] = None,
    ) -> List[dict]:
        """
        Retrieve top-k chunks for `question`.

        Heuristic improvement:
        - For cross-document questions that explicitly mention both PAPPG and Applicant Handbook,
          ensure we retrieve at least one chunk from each document_label so the generator
          has the material needed for comparisons/synthesis.
        """
        # 1) Optional filters
        where: Optional[dict] = None
        if filter_document:
            where = {"source_document": filter_document}
        elif filter_document_label:
            where = {"document_label": filter_document_label}

        # 2) Cross-document heuristic
        required_labels: List[str] = []
        lower = question.lower()
        if ("applicant" in lower and "handbook" in lower) or ("p-323" in lower) or ("p 323" in lower):
            required_labels.append("ApplicantHandbook")
        if ("pappg" in lower) or ("public assistance program policy guide" in lower) or ("policy guide" in lower):
            required_labels.append("PAPPG")

        # If label-based filters were explicitly requested, just run once.
        if where is not None or not required_labels or len(required_labels) == 1:
            primary = self._query_once(question, top_k=top_k, where=where)
            return self._enrich_with_cross_refs(question, primary, top_k, where)

        # 3) Retrieve general + each required doc_label, then merge ensuring coverage.
        general_chunks = self._query_once(question, top_k=top_k, where=None)

        per_label_k = max(1, min(top_k, 6))
        label_chunks: Dict[str, List[dict]] = {}
        for label in required_labels:
            label_chunks[label] = self._query_once(
                question,
                top_k=per_label_k,
                where={"document_label": label},
            )

        # Best chunk per label
        final: List[dict] = []
        used_ids: set[str] = set()
        for label in required_labels:
            candidates = label_chunks.get(label, [])
            if not candidates:
                continue
            best = candidates[0]  # already sorted by score desc
            final.append(best)
            used_ids.add(best["chunk_id"])

        merged_candidates = sorted(
            general_chunks + [c for chunks in label_chunks.values() for c in chunks],
            key=lambda c: c["score"],
            reverse=True,
        )

        for c in merged_candidates:
            if len(final) >= top_k:
                break
            if c["chunk_id"] in used_ids:
                continue
            final.append(c)
            used_ids.add(c["chunk_id"])

        return self._enrich_with_cross_refs(question, final, top_k, where)

    def count(self) -> int:
        self._load()
        if self._collection is None:
            return 0
        return self._collection.count()


# Module-level singleton so FastAPI reuses it across requests
retriever = Retriever()
