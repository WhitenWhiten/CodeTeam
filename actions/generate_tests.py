# actions/generate_tests.py
from __future__ import annotations
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

QA_PROMPT_FALLBACK = """你是QA。根据SDS为pytest生成测试套件与运行策略(run_command)。
输出严格JSON：{"tests": {"tests/test_xxx.py": "<content>"...}, "run_command": "pytest -q"}
SDS:
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

    def _build_prompt(self, sds: dict) -> str:
        import json
        return QA_PROMPT_FALLBACK.format(sds_json=json.dumps(sds, ensure_ascii=False, indent=2))

    async def run(self, sds, llm):
        prompt = self._build_prompt(sds)
        tests = await llm.files(prompt)
        run_command = "pytest -q"
        return {"tests": tests, "run_command": run_command}