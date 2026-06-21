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

QA_PROMPT_FALLBACK = """You are a QA engineer. Your task is to generate executable pytest tests and the corresponding test-run strategy from the selected SDS.

Output contract:
- Output exactly one JSON object that conforms to the `QA_TEST_BUNDLE` structure.
- The output format must be `{{"tests": {{"tests/<name>.py": "<content>"}}, "run_command": "pytest -q", "setup_commands": []}}`.
- Do not output Markdown, code fences, explanations, comments, or any extra prefix/suffix text.

Test-design requirements:
- Test files must be under the `tests/` directory.
- Test filenames should correspond to business modules or key flows, such as `tests/test_catalog.py`, `tests/test_cart.py`, or `tests/test_checkout.py`.
- Do not hardcode templated names such as `tests/test_main.py` or `tests/test_utils.py` unless they naturally follow from the current SDS module decomposition.
- Tests must cover core business flows, key boundary conditions, and major error paths.
- Tests may depend only on source interfaces declared in the SDS; do not invent nonexistent functions, classes, or modules.

Run-strategy requirements:
- Use `pytest -q` as the default `run_command`, unless the SDS explicitly requires something different that remains compatible with the current PoC.
- Include minimal installation or preparation commands in `setup_commands` only when truly necessary; otherwise return an empty array.

Input SDS:
{sds_json}
"""

class GenerateTestsAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # Compatible with metagpt.Action
        except TypeError:
        # Compatible with the local placeholder Action(name: str="")
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
