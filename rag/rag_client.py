from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())


class RAGClient:
    def __init__(self, cfg):
        self.cfg = cfg
        corpus_file = getattr(cfg, "corpus_file", None)
        if corpus_file:
            self.corpus_path = Path(corpus_file)
        else:
            self.corpus_path = Path(__file__).resolve().parent / "collection" / "github_repos.json"
        self.top_k = int(getattr(cfg, "top_k", 6))
        self.distinct_sources = bool(getattr(cfg, "distinct_sources", True))
        self.similarity_threshold = float(getattr(cfg, "similarity_threshold", 0.92))
        self._docs = self._load_docs()

    def _load_docs(self) -> List[Dict[str, object]]:
        if not self.corpus_path.exists():
            return []

        try:
            raw_docs = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        docs: List[Dict[str, object]] = []
        for item in raw_docs:
            source = str(item.get("full_name") or item.get("source") or "unknown")
            readme = str(item.get("readme") or "")
            tree = str(item.get("tree") or "")
            dependencies = str(item.get("dependencies") or item.get("dependency_manifest") or "")
            roles = str(item.get("file_roles") or item.get("interfaces") or "")
            snippet_parts = []
            if readme.strip():
                snippet_parts.append("README summary:\n" + readme[:900].strip())
            if tree.strip():
                snippet_parts.append("File tree pattern:\n" + tree[:700].strip())
            if dependencies.strip():
                snippet_parts.append("Dependency hints:\n" + dependencies[:400].strip())
            if roles.strip():
                snippet_parts.append("File-role/interface hints:\n" + roles[:500].strip())
            if not snippet_parts:
                continue
            snippet = "\n\n".join(snippet_parts)
            haystack = " ".join([source, readme, tree]).lower()
            tokens = set(_tokenize(haystack))
            docs.append(
                {
                    "source": source,
                    "snippet": snippet,
                    "tokens": tokens,
                    "haystack": haystack,
                    "fingerprint": set(_tokenize(snippet)),
                }
            )
        return docs

    def query(self, q: str) -> list[dict]:
        if not self._docs:
            return []

        query_tokens = set(_tokenize(q))
        if not query_tokens:
            return []

        query_text = q.lower().strip()
        ranked = []
        for doc in self._docs:
            overlap = len(query_tokens & doc["tokens"])
            phrase_bonus = 3 if query_text and query_text in doc["haystack"] else 0
            score = overlap + phrase_bonus
            if score <= 0:
                continue
            ranked.append((score, doc))

        ranked.sort(key=lambda item: item[0], reverse=True)
        results = []
        seen_sources = set()
        seen_fingerprints: list[set[str]] = []
        for score, doc in ranked:
            source = str(doc["source"])
            if self.distinct_sources and source in seen_sources:
                continue
            fingerprint = doc.get("fingerprint", set())
            if self._is_near_duplicate(fingerprint, seen_fingerprints):
                continue
            results.append(
                {
                    "text": doc["snippet"],
                    "meta": {
                        "source": source,
                        "score": score,
                        "retrieval_kind": "design_hint",
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
