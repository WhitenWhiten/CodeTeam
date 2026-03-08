# actions/generate_tests.py
from __future__ import annotations
import json
from pathlib import Path
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

from core.schemas import validate_qa_test_bundle

QA_PROMPT_FALLBACK = """你是 QA 工程师。你的任务是根据选定的 SDS 生成一组可执行的 pytest 测试，以及对应的测试运行策略。

输出契约：
- 只输出单个 JSON 对象，必须符合 `QA_TEST_BUNDLE` 结构。
- 输出格式必须为 `{{"tests": {{"tests/<name>.py": "<content>"}}, "run_command": "pytest -q", "setup_commands": []}}`。
- 不要输出 Markdown、代码块、解释、注释或任何额外前后缀文本。

测试设计要求：
- 测试文件必须位于 `tests/` 目录下。
- 测试文件名应与业务模块或关键流程对应，例如 `tests/test_catalog.py`、`tests/test_cart.py`、`tests/test_checkout.py`。
- 不要硬编码 `tests/test_main.py`、`tests/test_utils.py` 等模板化命名，除非它们确实由当前 SDS 的模块划分自然推出。
- 测试内容必须覆盖核心业务流程、关键边界条件和主要错误路径。
- 测试只能依赖 SDS 中声明的源码接口，不要虚构不存在的函数、类或模块。

运行策略要求：
- `run_command` 默认使用 `pytest -q`，除非 SDS 明确要求不同但仍兼容当前 PoC。
- 如确有必要，可在 `setup_commands` 中提供最小的前置安装或准备命令；否则返回空数组。

输入SDS：
{sds_json}
"""

class GenerateTestsAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # 兼容 metagpt.Action
        except TypeError:
        # 兼容我们自带的占位 Action(name: str="")
            super().__init__(name="GenerateTestsAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path(__file__).resolve().parents[1] / "prompts" / "qa_prompt.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return QA_PROMPT_FALLBACK

    def _build_prompt(self, sds: dict) -> str:
        tpl = self._load_prompt_template()
        return tpl.format(sds_json=json.dumps(sds, ensure_ascii=False, indent=2))

    async def run(self, sds, llm):
        prompt = self._build_prompt(sds)
        bundle = await llm.structured_json(prompt, schema="QA_TEST_BUNDLE")
        validate_qa_test_bundle(bundle)
        return bundle
