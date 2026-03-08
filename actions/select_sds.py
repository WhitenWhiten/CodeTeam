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

CTO_PROMPT_FALLBACK = """你是 CTO。你的任务是从多个候选 SDS 中选择最适合当前需求、且最适合当前执行器落地的一份方案。

输出契约：
- 只输出单个 JSON 对象，格式必须为 `{{"chosen_index": number, "rationale": string}}`。
- 不要输出 Markdown、代码块、解释、注释或任何额外前后缀文本。

评估维度：
- 可行性：方案能否完整覆盖用户需求并落地实现。
- 一致性：`repo_structure`、`file_specs`、`dev_plan` 是否彼此一致，是否存在明显遗漏或冲突。
- 可测试性：测试结构是否围绕业务模块、关键流程和边界条件组织，而不是依赖固定模板文件名。
- 并行开发友好度：模块职责是否清晰，Developer 之间的接口边界是否明确。
- 实施成本：在满足需求前提下，是否避免了不必要的复杂度和过度设计。

执行器约束：
- 当前 PoC 仅支持 `python + pytest`。
- 如果某个候选方案不满足上述执行器约束，应优先选择满足约束且整体质量最高的方案。

决策要求：
- 只能从给定 SDS 列表中选择，不要虚构新方案。
- 当多个方案接近时，优先选择结构更清晰、接口更稳定、测试策略更自然的一份。

用户需求：
{question}

候选SDS列表（JSON数组）：
{sds_list}

RAG参考（可选）：
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
