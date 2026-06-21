# actions/generate_sds.py
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

from core.schemas import validate_sds

ARCHITECT_PROMPT_FALLBACK = """You are a senior software architect. Your task is to produce an executable Software Design Specification (SDS) from the user's requirements for direct use by the CTO, Developer, and QA agents.

Output contract:
- Output exactly one JSON object that conforms to the SDS Schema.
- Do not output Markdown, code fences, explanations, comments, or any extra prefix/suffix text.
- The design must be directly usable by the current PoC: `tech_stack.language` must be `python`, and `tech_stack.test_framework` must be `pytest`.

Design requirements:
- `problem`: Restate the user's requirements accurately, covering the core goal, main business flows, and key boundaries.
- `tech_stack`: Provide the Python runtime, primary frameworks or libraries, and the minimal technical set needed to implement the request.
- `repo_structure`: List the complete repository structure and use directory-node `children` to express hierarchy; it must include business source directories and a `tests/` directory.
- Test files in `repo_structure` should correspond to real module responsibilities or business behavior, such as `tests/test_catalog.py`, `tests/test_cart.py`, or `tests/test_checkout.py`; do not hardcode `tests/test_main.py` or `tests/test_utils.py` unless they naturally follow from the current design.
- `file_specs`: Describe only source files implemented by Developers; every entry must include responsibilities, explicit function or class interfaces, and dependency file paths.
- Files referenced by `file_specs.dependencies` must come from the same `repo_structure`, and dependency direction should be clear and loosely coupled.
- `dev_plan`: Choose a reasonable number of Developers and assignments based on project complexity; every source file must be assigned to exactly one Developer; do not assign files under `tests/` to Developers.
- Consistency requirements: every `file_specs.path` must appear in `repo_structure`; `dev_plan` must cover every source `file_specs` entry exactly once, with no duplicate assignments.

Design preferences:
- Prefer small modules with clear responsibilities, explicit interfaces, and easy parallel development.
- Prefer stable public interfaces that reduce implicit coupling between Developers.
- Organize tests around business modules, key flows, and boundary conditions instead of fixed filename templates.
- This Architect's specific design preference: {design_preference}
- To keep candidate designs diverse, avoid reusing top-level module boundaries already claimed by other Architects; use only this summary as a reference and do not copy a full prior design: {claimed_summary}

RAG usage rules:
- If RAG references are provided, treat them as supplemental hints rather than hard constraints.
- When RAG references conflict with user requirements, prioritize the user requirements.

User requirements:
{question}

RAG references (optional):
{rag_snippets}
"""

class GenerateSDSAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # Compatible with metagpt.Action
        except TypeError:
        # Compatible with the local placeholder Action(name: str="")
            super().__init__(name="GenerateSDSAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path(__file__).resolve().parents[1] / "prompts" / "architect_prompt.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ARCHITECT_PROMPT_FALLBACK

    def _render_rag(self, docs: List[Dict[str, Any]]) -> str:
        if not docs:
            return ""
        parts = []
        for i, d in enumerate(docs[:8], 1):
            txt = d.get("text", "")
            src = d.get("meta", {}).get("source", "")
            parts.append(f"[{i}] {src}\n{txt}")
        return "\n\n".join(parts)

    def _build_prompt(
        self,
        q: str,
        rag_docs: List[Dict[str, Any]],
        design_preference: str = "",
        claimed_summary: str = "",
    ) -> str:
        tpl = self._load_prompt_template()
        return tpl.format(
            question=q,
            rag_snippets=self._render_rag(rag_docs),
            design_preference=design_preference or "balanced architecture",
            claimed_summary=claimed_summary or "No prior module claims.",
        )

    async def run(
        self,
        question: str,
        rag_client=None,
        design_preference: str = "",
        claimed_summary: str = "",
        return_trace: bool = False,
    ) -> Dict[str, Any]:
        rag_docs = rag_client.query(question) if rag_client else []
        prompt = self._build_prompt(question, rag_docs, design_preference, claimed_summary)
        sds_json = await self.llm.structured_json(prompt, schema="SDS")
        validate_sds(sds_json)
        if return_trace:
            return {"sds": sds_json, "rag_docs": rag_docs, "prompt": prompt}
        return sds_json
