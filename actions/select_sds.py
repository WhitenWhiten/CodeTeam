# actions/select_sds.py
from __future__ import annotations
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

CTO_PROMPT_FALLBACK = """You are the CTO. Your task is to choose, from multiple candidate SDS documents, the design that best fits the current requirements and is most suitable for execution by the current runtime.

Output contract:
- Output exactly one JSON object with this format: `{{"chosen_index": number, "rationale": string, "scores": {{"structural_validity": number, "interface_consistency": number, "implementability": number, "developer_plan": number}}}}`.
- `scores` may be omitted for backward compatibility; if provided, each score must be 0, 1, or 2.
- Do not output Markdown, code fences, explanations, comments, or any extra prefix/suffix text.

Evaluation dimensions:
- Feasibility: whether the design fully covers the user's requirements and can be implemented.
- Consistency: whether `repo_structure`, `file_specs`, and `dev_plan` agree with each other and avoid obvious omissions or conflicts.
- Testability: whether the test structure is organized around business modules, key flows, and boundary conditions instead of fixed template filenames.
- Parallel-development friendliness: whether module responsibilities are clear and interfaces between Developers are explicit.
- Implementation cost: whether the design avoids unnecessary complexity and overengineering while still satisfying the requirements.

Executor constraints:
- The current PoC supports only `python + pytest`.
- If a candidate does not satisfy these executor constraints, prefer the highest-quality candidate that does.

Decision requirements:
- Choose only from the given SDS list; do not invent a new design.
- When multiple designs are close, prefer the one with clearer structure, more stable interfaces, and a more natural test strategy.
- Candidate SDS documents have already passed contract validation; `chosen_index` must be a valid index in the candidate SDS list.

User requirements:
{question}

Candidate SDS list (JSON array):
{sds_list}

RAG references (optional):
{rag_snippets}
"""

class SelectSDSAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # Compatible with metagpt.Action
        except TypeError:
        # Compatible with the local placeholder Action(name: str="")
            super().__init__(name="SelectSDSAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path(__file__).resolve().parents[1] / "prompts" / "cto_prompt.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return CTO_PROMPT_FALLBACK

    def _render_rag(self, docs: List[Dict[str, Any]]) -> str:
        if not docs:
            return ""
        return "\n\n".join([d.get("text", "") for d in docs[:6]])

    def _build_prompt(self, question: str, sds_list: List[Dict[str, Any]], rag_client=None) -> str:
        rag_docs = rag_client.query(question) if rag_client else []
        normalized_sds_list, _ = self._valid_normalized_candidates(sds_list)
        tpl = self._load_prompt_template()
        return tpl.format(
            question=question,
            sds_list=json.dumps(normalized_sds_list, ensure_ascii=False, indent=2),
            rag_snippets=self._render_rag(rag_docs),
        )

    def _valid_normalized_candidates(self, sds_list: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
        valid = []
        errors = []
        for idx, candidate in enumerate(sds_list):
            try:
                normalized = normalize_sds_candidate(candidate)
                validate_sds(normalized)
            except Exception as exc:
                errors.append(f"candidate {idx}: {exc}")
                continue
            valid.append(normalized)
        return valid, errors

    def _chosen_index_or_fallback(self, result: Dict[str, Any], candidate_count: int) -> int:
        try:
            idx = int(result.get("chosen_index", 0))
        except (TypeError, ValueError):
            return 0
        if idx < 0 or idx >= candidate_count:
            return 0
        return idx

    async def run(self, question: str, sds_list: List[Dict[str, Any]], rag_client=None) -> Dict[str, Any]:
        valid_sds_list, errors = self._valid_normalized_candidates(sds_list)
        if not valid_sds_list:
            raise ValueError(f"no valid SDS candidates. errors={errors}")

        prompt = self._build_prompt(question, valid_sds_list, rag_client)
        result = await self.llm.structured_json(prompt, schema="CTO_DECISION")
        if not isinstance(result, dict):
            result = {}
        idx = self._chosen_index_or_fallback(result, len(valid_sds_list))
        response = {"chosen_sds": valid_sds_list[idx], "rationale": result.get("rationale", "")}
        if "scores" in result:
            response["scores"] = result["scores"]
        return response
