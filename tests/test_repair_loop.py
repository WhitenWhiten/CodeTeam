import asyncio
from pathlib import Path

from app.config import SystemConfig
from app.bootstrap import bootstrap
from core.llm import LLMClient
from core.contracts import RunStatus
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync
from orchestrator.scheduler import DependencyScheduler


class RepairModel(LLMClient):
    def __init__(self, cfg, repair=True):
        super().__init__(cfg)
        self.catalog_calls = 0
        self.repair = repair

    async def text(self, prompt):
        result = await super().text(prompt)
        if prompt.startswith("# FILE_PATH: shop/catalog.py"):
            self.catalog_calls += 1
            if self.catalog_calls == 1 or not self.repair:
                return result.replace("return float(product[\"price\"])", "return 1 / 0")
        return result


def run_case(tmp_path, repairs=1, repair=True):
    cfg = SystemConfig(workspace=str(tmp_path / "workspace"), artifacts_dir=str(tmp_path / "artifacts"), max_rounds=repairs)
    cfg.git.enabled = False
    ctx = bootstrap(cfg)
    ctx.llm = RepairModel(cfg.llm, repair=repair)
    return asyncio.run(MultiAgentCodegenWorkflowAsync(ctx).run(cfg.user_question))


def test_last_allowed_repair_is_revalidated(tmp_path):
    result = run_case(tmp_path)
    assert result.status == RunStatus.SUCCESS, result.reason
    assert result.repairs == 1
    assert result.qa["scope"] == "full"
    assert result.qa["counts"]["passed"] == 4
    assert not (Path(result.repo_root) / ".codeteam_qa").exists()


def test_zero_repair_budget_still_tests_and_reports_failure(tmp_path):
    result = run_case(tmp_path, repairs=0)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert result.qa and not result.qa["success"]


def test_unchanged_broken_code_stops_without_consuming_all_rounds(tmp_path):
    result = run_case(tmp_path, repairs=5, repair=False)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert "no progress" in result.reason.lower()
    assert result.repairs == 1


def test_symbol_dependency_blocks_consumer():
    specs = [{"path": "a.py", "interfaces": {"functions": [{"name": "f", "signature": "def f():"}], "classes": []}, "dependencies": []},
             {"path": "b.py", "interfaces": {"functions": [], "classes": []}, "dependencies": ["a.py::f"]}]
    scheduler = DependencyScheduler(specs, [{"developer_id": "D", "file_paths": ["a.py", "b.py"]}])
    assert scheduler.ready_files() == ["a.py"]
    scheduler.complete(scheduler.dispatch_ready()[0].file_path)
    assert scheduler.ready_files() == ["b.py"]
