# actions/select_sds.py
from __future__ import annotations
from core.mechanism_state import count
import json
from pathlib import Path
from typing import List, Dict, Any
from core.schemas import validate_sds
from utils.sds_normalizer import normalize_sds_candidate
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

from core.planning_contracts import rank_candidates

CTO_PROMPT_FALLBACK = """You are the CTO. Compare every candidate against the user requirements and executor constraints.
Output one JSON object with evaluations, one row per candidate_id. Each row must contain candidate_id, scores, rationale, and assumptions (a list of undeclared assumptions, empty if none).
Scores must contain exactly structural_validity, interface_consistency, implementability, developer_plan. Every score is an integer 0, 1, or 2. Justify the scores; do not select by candidate order.
All candidates have already passed mechanical validation. Assess interface consistency, requirement coverage, implementability under dependencies/resources, and developer count/ownership. Supported execution: python + pytest.
The runtime computes total and ranks by descending total, then fewer declared assumptions, lower maximum fan-out, fewer edges, original order. Do not return chosen_index or invent candidates.
User requirements:
{question}
CANDIDATES_JSON
{sds_list}
END_CANDIDATES
RAG references (optional):
{rag_snippets}
"""

class SelectSDSAction(Action):
    def __init__(self, llm=None):
        try: super().__init__()
        except TypeError: super().__init__(name="SelectSDSAction")
        self.llm = llm

    def _load_prompt_template(self):
        p = Path(__file__).resolve().parents[1] / "prompts" / "cto_prompt.md"
        return p.read_text(encoding="utf-8") if p.exists() else CTO_PROMPT_FALLBACK

    def _valid_normalized_candidates(self, sds_list):
        valid, errors = [], []
        for index, candidate in enumerate(sds_list):
            try:
                normalized = normalize_sds_candidate(candidate)
                validate_sds(normalized)
                valid.append({"candidate_id": f"candidate-{index:04d}", "source_index": index, "sds": normalized})
            except Exception as exc:
                errors.append({"source_index": index, "reason": str(exc)})
        return valid, errors

    def _render_rag(self, docs):
        from rag.information import render_documents
        return render_documents(docs)

    def _build_prompt(self, question, sds_list, rag_client=None):
        candidates, _ = self._valid_normalized_candidates(sds_list)
        rag_docs = rag_client.query(question) if rag_client else []
        return self._load_prompt_template().format(question=question,
            sds_list=json.dumps(candidates, ensure_ascii=False, indent=2), rag_snippets=self._render_rag(rag_docs))

    async def run(self, question, sds_list, rag_client=None):
        candidates, errors = self._valid_normalized_candidates(sds_list)
        if not candidates: raise ValueError(f"no valid SDS candidates. errors={errors}")
        prompt = self._build_prompt(question, sds_list, rag_client)
        attempts = []
        for attempt in range(3):
            count(self.llm, "cto_attempts", retry=attempt)
            result = await self.llm.structured_json(prompt, schema="CTO_DECISION")
            try:
                ranked = rank_candidates(result, candidates)
                break
            except (ValueError, TypeError, __import__('jsonschema').ValidationError) as exc:
                attempts.append({"response": result, "error": str(exc)})
                if attempt == 2: raise ValueError(f"Invalid CTO ranking after retries: {exc}") from exc
                prompt += "\nPrevious response rejected: " + str(exc) + "\nScore every listed candidate using the required contract."
        lookup = {c["candidate_id"]: c for c in candidates}
        for selected in ranked:
            chosen = lookup[selected["candidate_id"]]["sds"]
            try: validate_sds(chosen)
            except Exception as exc:
                errors.append({"candidate_id": selected["candidate_id"], "reason": str(exc)})
                continue
            return {"chosen_sds": chosen, "candidate_id": selected["candidate_id"], "rationale": selected["rationale"],
                    "scores": selected["scores"], "ranking": ranked, "rejected_candidates": errors, "decision_retries": attempts}
        raise ValueError("All ranked candidates failed final validation")
