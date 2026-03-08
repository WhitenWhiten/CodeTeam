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

ARCHITECT_PROMPT_FALLBACK = """你是资深软件架构师。你的任务是根据用户需求输出一个可执行的软件设计方案（SDS），供 CTO、Developer 和 QA agent 直接消费。

输出契约：
- 只输出单个 JSON 对象，必须符合 SDS Schema。
- 不要输出 Markdown、代码块、解释、注释或任何额外前后缀文本。
- 方案必须可直接用于当前 PoC：`tech_stack.language` 必须为 `python`，`tech_stack.test_framework` 必须为 `pytest`。

设计要求：
- `problem`：准确重述用户需求，覆盖核心目标、主要业务流程和关键边界。
- `tech_stack`：给出 Python 运行时、主要框架或库，以及实现该需求所需的最小技术集合。
- `repo_structure`：列出完整仓库结构，并用目录节点的 `children` 表达层级；必须包含业务源码目录与 `tests/` 目录。
- `repo_structure` 中的测试文件应与实际模块职责或业务行为对应，例如 `tests/test_catalog.py`、`tests/test_cart.py`、`tests/test_checkout.py`；不要硬编码 `tests/test_main.py` 或 `tests/test_utils.py`，除非它们确实由当前设计自然推出。
- `file_specs`：只描述由 Developer 负责实现的源码文件；每个条目必须包含职责说明、明确的函数或类接口，以及依赖文件路径。
- `file_specs.dependencies` 中引用的文件必须来自同一份 `repo_structure`，并尽量保持依赖方向清晰、低耦合。
- `dev_plan`：根据项目复杂度给出合理的 Developer 数量与分工；每个源码文件必须且只能分配给一个 Developer；不要把 `tests/` 下文件分配给 Developer。
- 一致性要求：`file_specs.path` 必须全部出现在 `repo_structure` 中；`dev_plan` 必须完整覆盖全部源码 `file_specs`，且不能重复分配。

设计偏好：
- 优先拆分为职责清晰、接口明确、便于并行开发的小模块。
- 优先让公共接口稳定，减少 Developer 之间的隐式耦合。
- 测试结构应围绕业务模块、关键流程和边界条件组织，而不是沿用固定文件名模板。

RAG 使用规则：
- 如果提供了 RAG 参考，将其视为补充线索而不是硬约束。
- 当 RAG 参考与用户需求冲突时，优先满足用户需求。

用户需求：
{question}

RAG参考（可选）：
{rag_snippets}
"""

class GenerateSDSAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # 兼容 metagpt.Action
        except TypeError:
        # 兼容我们自带的占位 Action(name: str="")
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

    def _build_prompt(self, q: str, rag_docs: List[Dict[str, Any]]) -> str:
        tpl = self._load_prompt_template()
        return tpl.format(question=q, rag_snippets=self._render_rag(rag_docs))

    async def run(self, question: str, rag_client=None) -> Dict[str, Any]:
        rag_docs = rag_client.query(question) if rag_client else []
        prompt = self._build_prompt(question, rag_docs)
        sds_json = await self.llm.structured_json(prompt, schema="SDS")
        validate_sds(sds_json)
        return sds_json
