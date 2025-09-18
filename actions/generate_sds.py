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

ARCHITECT_PROMPT_FALLBACK = """你是资深软件架构师。输出严格JSON，符合SDS Schema。
要求：
- tech_stack: 必须使用 language=python，test_framework=pytest
- repo_structure: 列出全部文件与目录；必须包含 tests/test_main.py 与 tests/test_utils.py
- file_specs: 每个文件的职责、接口定义（函数/类签名），以及依赖文件路径
- dev_plan: 每个源码文件唯一分配给某个Developer（例如 Dev-1、Dev-2）；不要分配 tests/ 下文件
- 一致性：file_specs.path 必须出现在 repo_structure；dev_plan 覆盖所有源码 file_specs 且不重复
- 输出仅为单个JSON，不要附加说明文本

Q:
{question}

RAG参考(可选):
{rag_snippets}
"""

class GenerateSDSAction(Action):
    name = "GenerateSDSAction"

    def __init__(self, llm=None):
        super().__init__(self.name)
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path("prompts/architect_prompt.md")
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

    def _build_prompt(self, q: str, rag_docs: List[Dict[str, Any]]) -> str:
        tpl = self._load_prompt_template()
        return tpl.format(question=q, rag_snippets=self._render_rag(rag_docs))

    async def run(self, question: str, rag_client=None) -> Dict[str, Any]:
        rag_docs = rag_client.query(question) if rag_client else []
        prompt = self._build_prompt(question, rag_docs)
        sds_json = await self.llm.structured_json(prompt, schema="SDS")
        validate_sds(sds_json)
        return sds_json