from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())


def _l2_normalize(vectors: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, eps)


class RAGClient:
    """Design-reference retrieval for the Architect stage.

    The primary path follows the paper setup: compact repository summaries are
    chunked, embedded with BGE-M3 by default, and indexed with FAISS HNSW for
    cosine-similarity retrieval. A lexical fallback remains available for local
    smoke tests or minimal installations.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        corpus_file = getattr(cfg, "corpus_file", None)
        self.corpus_path = (
            Path(corpus_file)
            if corpus_file
            else Path(__file__).resolve().parent / "collection" / "github_repos.json"
        )
        self.index_dir = Path(getattr(cfg, "index_dir", "./rag"))
        self.top_k = int(getattr(cfg, "top_k", 5))
        self.distinct_sources = bool(getattr(cfg, "distinct_sources", True))
        self.similarity_threshold = float(getattr(cfg, "similarity_threshold", 0.92))
        self.chunk_tokens = int(getattr(cfg, "chunk_tokens", 768))
        self.chunk_overlap = int(getattr(cfg, "chunk_overlap", 128))
        self.embedding_model = str(getattr(cfg, "embedding_model", "BAAI/bge-m3"))
        self.index_backend = str(getattr(cfg, "index_backend", "faiss_hnsw")).lower()
        self.fallback_mode = str(getattr(cfg, "fallback_mode", "lexical")).lower()

        self._chunks = self._load_chunks()
        self._vector_ready = False
        self._index = None
        self._embeddings: np.ndarray | None = None
        self._model = None

        if self._chunks and self.index_backend != "lexical":
            try:
                self._prepare_vector_index()
            except Exception:
                if self.fallback_mode != "lexical":
                    raise

    def query(self, q: str) -> list[dict]:
        if not self._chunks:
            return []
        if self._vector_ready:
            return self._query_vector(q)
        return self._query_lexical(q)

    def _load_chunks(self) -> List[Dict[str, Any]]:
        if not self.corpus_path.exists():
            return []
        try:
            raw_docs = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        chunks: List[Dict[str, Any]] = []
        for item in raw_docs:
            source = str(item.get("full_name") or item.get("source") or "unknown")
            compact_doc = self._compact_repo_text(item)
            if not compact_doc.strip():
                continue
            for chunk_id, text in enumerate(self._chunk_text(compact_doc)):
                tokens = set(_tokenize(" ".join([source, text])))
                chunks.append(
                    {
                        "text": text,
                        "source": source,
                        "chunk_id": chunk_id,
                        "tokens": tokens,
                        "fingerprint": set(_tokenize(text)),
                    }
                )
        return chunks

    def _compact_repo_text(self, item: Dict[str, Any]) -> str:
        parts = []
        readme = str(item.get("readme_summary") or item.get("summary") or item.get("readme") or "")
        tree = str(item.get("file_tree") or item.get("tree") or "")
        dependencies = str(item.get("dependencies") or item.get("dependency_manifest") or "")
        roles = str(item.get("file_roles") or item.get("interfaces") or item.get("exports") or "")

        if readme.strip():
            parts.append("README summary:\n" + readme.strip())
        if tree.strip():
            parts.append("File tree pattern:\n" + tree.strip())
        if dependencies.strip():
            parts.append("Dependency hints:\n" + dependencies.strip())
        if roles.strip():
            parts.append("File-role/interface hints:\n" + roles.strip())
        return "\n\n".join(parts)

    def _chunk_text(self, text: str) -> List[str]:
        tokens = _tokenize(text)
        if not tokens:
            return []
        if len(tokens) <= self.chunk_tokens:
            return [text[:6000].strip()]

        raw_words = re.findall(r"\S+", text)
        approx_ratio = max(1, math.ceil(len(raw_words) / len(tokens)))
        window = max(1, self.chunk_tokens * approx_ratio)
        overlap = min(window - 1, max(0, self.chunk_overlap * approx_ratio))
        step = max(1, window - overlap)

        chunks = []
        for start in range(0, len(raw_words), step):
            chunk = " ".join(raw_words[start : start + window]).strip()
            if chunk:
                chunks.append(chunk[:6000])
            if start + window >= len(raw_words):
                break
        return chunks

    def _prepare_vector_index(self) -> None:
        embeddings_path = self._cache_path("embeddings", ".npy")
        meta_path = self._cache_path("chunks", ".json")
        cached_embeddings = self._load_cached_embeddings(embeddings_path, meta_path)
        if cached_embeddings is None:
            model = self._load_embedding_model()
            texts = [chunk["text"] for chunk in self._chunks]
            cached_embeddings = model.encode(
                texts,
                convert_to_numpy=True,
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            cached_embeddings = np.asarray(cached_embeddings, dtype="float32")
            cached_embeddings = _l2_normalize(cached_embeddings)
            embeddings_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(embeddings_path, cached_embeddings)
            meta_path.write_text(
                json.dumps(self._chunk_cache_signature(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        self._embeddings = np.asarray(cached_embeddings, dtype="float32")
        self._index = self._build_faiss_hnsw(self._embeddings)
        self._vector_ready = True

    def _load_embedding_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(
                "Vector RAG requires sentence-transformers. Install optional RAG "
                "dependencies or set CODETEAM_RAG_BACKEND=lexical."
            ) from exc
        self._model = SentenceTransformer(self.embedding_model)
        return self._model

    def _build_faiss_hnsw(self, embeddings: np.ndarray):
        try:
            import faiss
        except Exception as exc:
            raise RuntimeError(
                "Vector RAG requires faiss. Install faiss-cpu or set "
                "CODETEAM_RAG_BACKEND=lexical."
            ) from exc

        dim = embeddings.shape[1]
        index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = 200
        index.hnsw.efSearch = 64
        index.add(embeddings)
        return index

    def _query_vector(self, q: str) -> list[dict]:
        if not q.strip() or self._index is None:
            return []
        model = self._load_embedding_model()
        query_embedding = model.encode(
            [q],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        query_embedding = _l2_normalize(np.asarray(query_embedding, dtype="float32"))
        candidate_count = min(len(self._chunks), max(self.top_k * 8, self.top_k))
        scores, indexes = self._index.search(query_embedding, candidate_count)
        ranked = [
            (float(score), int(idx))
            for score, idx in zip(scores[0].tolist(), indexes[0].tolist())
            if idx >= 0
        ]
        return self._format_ranked_results(ranked, retrieval_kind="design_hint_vector")

    def _query_lexical(self, q: str) -> list[dict]:
        query_tokens = set(_tokenize(q))
        if not query_tokens:
            return []

        ranked = []
        for idx, chunk in enumerate(self._chunks):
            overlap = len(query_tokens & chunk["tokens"])
            if overlap <= 0:
                continue
            ranked.append((float(overlap), idx))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return self._format_ranked_results(ranked, retrieval_kind="design_hint_lexical")

    def _format_ranked_results(
        self, ranked: Sequence[tuple[float, int]], retrieval_kind: str
    ) -> list[dict]:
        results = []
        seen_sources = set()
        seen_fingerprints: list[set[str]] = []

        for score, idx in ranked:
            chunk = self._chunks[idx]
            source = str(chunk["source"])
            if self.distinct_sources and source in seen_sources:
                continue
            fingerprint = chunk.get("fingerprint", set())
            if self._is_near_duplicate(fingerprint, seen_fingerprints):
                continue
            results.append(
                {
                    "text": chunk["text"],
                    "meta": {
                        "source": source,
                        "score": score,
                        "chunk_id": chunk["chunk_id"],
                        "retrieval_kind": retrieval_kind,
                        "embedding_model": self.embedding_model if self._vector_ready else None,
                        "index_backend": "faiss_hnsw" if self._vector_ready else "lexical",
                    },
                }
            )
            seen_sources.add(source)
            seen_fingerprints.append(fingerprint)
            if len(results) >= self.top_k:
                break
        return results

    def _is_near_duplicate(self, fingerprint: set[str], seen: list[set[str]]) -> bool:
        if not fingerprint:
            return False
        for prior in seen:
            union = fingerprint | prior
            if not union:
                continue
            similarity = len(fingerprint & prior) / len(union)
            if similarity >= self.similarity_threshold:
                return True
        return False

    def _cache_path(self, prefix: str, suffix: str) -> Path:
        digest = hashlib.sha256()
        digest.update(str(self.corpus_path.resolve()).encode("utf-8"))
        digest.update(self.corpus_path.read_bytes() if self.corpus_path.exists() else b"")
        digest.update(self.embedding_model.encode("utf-8"))
        digest.update(f"{self.chunk_tokens}:{self.chunk_overlap}".encode("utf-8"))
        name = f"{prefix}_{digest.hexdigest()[:16]}{suffix}"
        return self.index_dir / "collection" / "cache" / name

    def _chunk_cache_signature(self) -> list[dict]:
        return [
            {
                "source": chunk["source"],
                "chunk_id": chunk["chunk_id"],
                "text_hash": hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest(),
            }
            for chunk in self._chunks
        ]

    def _load_cached_embeddings(self, embeddings_path: Path, meta_path: Path) -> np.ndarray | None:
        if not embeddings_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta != self._chunk_cache_signature():
                return None
            embeddings = np.load(embeddings_path)
            if embeddings.shape[0] != len(self._chunks):
                return None
            return np.asarray(embeddings, dtype="float32")
        except Exception:
            return None
