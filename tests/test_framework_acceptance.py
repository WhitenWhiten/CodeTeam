import asyncio
import json
import os
import shutil
import venv
from pathlib import Path
import pytest
from app.bootstrap import bootstrap
from app.config import SystemConfig
from core.llm import LLMClient
from orchestrator.workflow import MultiAgentCodegenWorkflow
from runtime_adapters.python_runtime import PythonRuntime
from actions.run_tests import RunTestsAction
from roles.qa_agent_async import QAAgentAsync
from utils.sds_parser import parse_sds
from types import SimpleNamespace
from core.schemas import validate_sds


class CounterModel(LLMClient):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.service_calls = 0

    async def structured_json(self, prompt, schema=None):
        if schema == "SDS":
            return {"id": "counter", "problem": "count steps",
                "tech_stack": {"language": "python", "frameworks": [], "runtime": "python3.11", "test_framework": "pytest"},
                "repo_structure": [{"path": path, "type": "file"} for path in ["src/domain.py", "src/service.py", "tests/test_count.py"]],
                "file_specs": [
                    {"path": "src/domain.py", "responsibilities": "counter", "owner": "Domain", "dependencies": [],
                     "interfaces": {"functions": [], "classes": [{"name": "Counter", "init_signature": "def __init__(self, initial: int = 0):",
                        "methods": [{"name": "add", "signature": "def add(self, amount: int = 1) -> int:"}]}]}},
                    {"path": "src/service.py", "responsibilities": "count step service", "owner": "Service", "dependencies": ["src/domain.py::Counter"],
                     "interfaces": {"functions": [{"name": "count_steps", "signature": "def count_steps(start: int, steps: int) -> int:"}], "classes": []}}],
                "dev_plan": [{"developer_id": "Domain", "file_paths": ["src/domain.py"]}, {"developer_id": "Service", "file_paths": ["src/service.py"]}]}
        if schema == "QA_TEST_BUNDLE":
            return {"tests": {"tests/test_count.py": "from service import count_steps\n\ndef test_count():\n    assert count_steps(3, 2) == 5\n"}, "run_command": "pytest -q", "setup_commands": []}
        return await super().structured_json(prompt, schema)

    async def text(self, prompt):
        if prompt.startswith("# FILE_PATH: src/domain.py"):
            return "class Counter:\n    def __init__(self, initial: int = 0):\n        self.value = initial\n    def add(self, amount: int = 1) -> int:\n        self.value += amount\n        return self.value\n"
        assert '"init_signature"' in prompt and "def add" in prompt
        self.service_calls += 1
        body = 'raise ValueError("repair required")' if self.service_calls == 1 else 'return Counter(start).add(steps)'
        if self.service_calls > 1:
            assert 'raise ValueError' in prompt and 'test_count' in prompt
        return f"from domain import Counter\n\ndef count_steps(start: int, steps: int) -> int:\n    {body}\n"


@pytest.mark.parametrize("git_enabled,fixed", [(False, False), (False, True), (True, True)])
def test_class_src_layout_symbol_dependency_and_real_repair(tmp_path, git_enabled, fixed):
    if git_enabled and not shutil.which("git"):
        pytest.skip("git required")
    cfg = SystemConfig(workspace=str(tmp_path), architects=1, max_rounds=1)
    cfg.git.enabled = git_enabled
    cfg.developer_allocation.dynamic_enabled = not fixed
    cfg.developer_allocation.assignment_seed = 4
    ctx = bootstrap(cfg)
    ctx.llm = CounterModel(cfg.llm)
    result = MultiAgentCodegenWorkflow(ctx).run_sync("count steps")
    assert result.success, result.reason
    assert result.repairs == 1 and result.qa["counts"]["passed"] == 1
    assert result.qa["scope"] == "full"
    assert not (Path(result.repo_root) / ".codeteam_qa").exists()
    checkpoint = ctx.artifacts.read_json("checkpoint.json")
    assert len(checkpoint["completed"]) == 2
    assert "Counter" in json.dumps(checkpoint["briefs"])


def test_missing_pytest_reports_environment_failure_without_substitute(tmp_path):
    environment = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=False).create(environment)
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    result = PythonRuntime(str(executable)).run_tests(str(tmp_path), "pytest -q")
    assert not result["success"] and result["status"] == "environment_error"
    assert result["failures"][0]["category"] == "environment_error"


def test_qa_command_preserves_quoted_test_paths(tmp_path):
    result = asyncio.run(RunTestsAction().run(str(tmp_path), 'pytest -q "tests/test space.py"', PythonRuntime(),
        tests={"tests/test space.py": "def test_ok(): assert True\n"}))
    assert result["success"], result["output"]


def test_batch_defers_explicit_test_target_until_its_dependencies_are_ready():
    model = LLMClient(SimpleNamespace(provider="mock"))
    sds = parse_sds(model._mock_sds())
    qa = QAAgentAsync(model, SimpleNamespace(), None, None, sds=sds)
    qa.tests = model._mock_tests()
    qa.run_command = "pytest -q tests/test_checkout.py"
    assert qa._ready_tests({"shop/catalog.py"}) == {}
    assert qa._ready_tests({"shop/catalog.py", "shop/cart.py", "main.py"})


def test_sds_rejects_case_aliases_before_workspace_creation():
    model = LLMClient(SimpleNamespace(provider="mock"))
    sds = model._mock_sds()
    sds["repo_structure"].append({"path": "Main.py", "type": "file"})
    with pytest.raises(ValueError, match="case-insensitive"):
        validate_sds(sds)
