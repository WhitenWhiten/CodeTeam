import asyncio
import json
from types import SimpleNamespace

from core.contracts import RunStatus
from orchestrator.workflow import MultiAgentCodegenWorkflow
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync
from utils.run_artifacts import RunArtifacts


def context(tmp_path):
    return SimpleNamespace(cfg=SimpleNamespace(max_wall_clock_seconds=None),
                           artifacts=RunArtifacts(str(tmp_path)))


def test_sync_and_async_use_same_engine_and_report_failure(tmp_path):
    class Failing(MultiAgentCodegenWorkflow):
        async def _execute(self, question):
            self._set_stage("implementation")
            self._dev_tasks.append(asyncio.create_task(asyncio.sleep(100)))
            raise ValueError("broken implementation")
    wf = Failing(context(tmp_path))
    result = wf.run_sync("task")
    assert result.status == RunStatus.ERROR
    assert result.stage == "implementation"
    assert all(t.done() for t in wf._dev_tasks)
    assert json.loads((tmp_path / "repository/final.json").read_text())["status"] == "error"
    assert MultiAgentCodegenWorkflow.run is MultiAgentCodegenWorkflowAsync.run


def test_wall_limit_cancels_engine_and_returns_budget_status(tmp_path):
    class Slow(MultiAgentCodegenWorkflow):
        async def _execute(self, question):
            await asyncio.sleep(10)
    ctx = context(tmp_path)
    ctx.cfg.max_wall_clock_seconds = 0.02
    assert Slow(ctx).run_sync("task").status == RunStatus.BUDGET_EXHAUSTED


def test_cancel_propagates_after_cleanup(tmp_path):
    async def scenario():
        class Slow(MultiAgentCodegenWorkflowAsync):
            async def _execute(self, question):
                self._dev_tasks.append(asyncio.create_task(asyncio.sleep(100)))
                await asyncio.sleep(100)
        wf = Slow(context(tmp_path))
        task = asyncio.create_task(wf.run("task"))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert wf.result.status == RunStatus.CANCELLED
        assert all(t.done() for t in wf._dev_tasks)
    asyncio.run(scenario())
