import json
from types import SimpleNamespace as NS
import numpy as np
import pytest
from rag.rag_client import RAGClient


def config(tmp_path, **overrides):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([{"full_name": "demo/shop", "readme": "shop cart checkout"}]))
    return NS(corpus_file=str(corpus), index_dir=str(tmp_path), **{"index_backend": "lexical", **overrides})


def test_fallback_is_observable_and_can_be_forbidden(tmp_path, monkeypatch):
    def unavailable(self):
        raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(RAGClient, "_prepare_vector_index", unavailable)
    cfg = config(tmp_path, index_backend="faiss_hnsw")
    client = RAGClient(cfg)
    result = client.query("shop")
    assert result[0]["meta"]["retrieval_kind"] == "design_hint"
    assert result[0]["meta"]["index_backend"] == "lexical"
    assert "unavailable" in client.history[0]["status"]["fallback_reason"]
    cfg.fallback_mode = "error"
    with pytest.raises(RuntimeError, match="unavailable"):
        RAGClient(cfg)


def test_query_failure_uses_configured_fallback(tmp_path, monkeypatch):
    client = RAGClient(config(tmp_path))
    client._vector_ready = True
    def fail(q):
        raise ValueError("dimension mismatch")
    monkeypatch.setattr(client, "_query_vector", fail)
    assert client.query("shop")[0]["meta"]["index_backend"] == "lexical"
    assert client.status["fallback_reason"] == "ValueError: dimension mismatch"


def test_vector_cache_is_reused_and_corruption_rebuilt(tmp_path, monkeypatch):
    encoded = []
    class Embeddings:
        def encode(self, texts, **kwargs):
            encoded.append(texts)
            return np.array([[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(RAGClient, "_load_embedding_model", lambda self: Embeddings())
    monkeypatch.setattr(RAGClient, "_build_faiss_hnsw", lambda self, vectors: object())
    cfg = config(tmp_path, index_backend="faiss_hnsw")
    first = RAGClient(cfg)
    second = RAGClient(cfg)
    assert len(encoded) == 1 and second.status["active_backend"] == "faiss_hnsw"
    first._cache_path("embeddings", ".npy").write_bytes(b"truncated")
    RAGClient(cfg)
    assert len(encoded) == 2
    cfg.embedding_model = "different-model"
    RAGClient(cfg)
    assert len(encoded) == 3


@pytest.mark.parametrize("matrix", [np.array([1]), np.array([[np.nan, 1]]), np.array([[0., 0.]])])
def test_invalid_vectors_are_rejected(matrix):
    with pytest.raises(ValueError):
        RAGClient._validate_embeddings(matrix, 1)


def test_invalid_corpus_and_config_fail_explicitly(tmp_path):
    cfg = config(tmp_path)
    cfg.top_k = 0
    with pytest.raises(ValueError, match="bounds"):
        RAGClient(cfg)
    cfg.top_k = 1
    (tmp_path / "corpus.json").write_text("{}")
    with pytest.raises(ValueError, match="array"):
        RAGClient(cfg)
    (tmp_path / "corpus.json").unlink()
    with pytest.raises(FileNotFoundError):
        RAGClient(cfg)
