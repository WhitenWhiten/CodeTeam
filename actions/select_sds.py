# actions/select_sds.py
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

CTO_PROMPT_FALLBACK = """你是CTO。对给定的多份SDS进行评分，维度：可行性、复杂度、成本、可测试性、一致性。
若所选技术栈非python，请改选最优的python方案。
输出严格JSON：{"chosen_index": number, "rationale": string}

输入：
Q:
{question}

SDS列表(JSON数组，请逐份评估并选择索引):
{sds_list}

RAG参考(可选):
{rag_snippets}
"""

class SelectSDSAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # 兼容 metagpt.Action
        except TypeError:
        # 兼容我们自带的占位 Action(name: str="")
            super().__init__(name="SelectSDSAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path("prompts/cto_prompt.md")
        if p.exists():
            return p.read_text(encoding="utf-8")
        return CTO_PROMPT_FALLBACK

    def _render_rag(self, docs: List[Dict[str, Any]]) -> str:
        if not docs:
            return ""
        return "\n\n".join([d.get("text", "") for d in docs[:6]])

    def _build_prompt(self, question: str, sds_list: List[Dict[str, Any]], rag_client=None) -> str:
        rag_docs = rag_client.query(question) if rag_client else []
        tpl = self._load_prompt_template()
        return tpl.format(
            question=question,
            sds_list=json.dumps(sds_list, ensure_ascii=False, indent=2),
            rag_snippets=self._render_rag(rag_docs),
        )

    async def run(self, question: str, sds_list: List[Dict[str, Any]], rag_client=None) -> Dict[str, Any]:
        prompt = self._build_prompt(question, sds_list, rag_client)
        result = await self.llm.structured_json(prompt, schema="CTO_DECISION")
        idx = int(result.get("chosen_index", 0))
        return {"chosen_sds": sds_list[idx], "rationale": result.get("rationale", "")}