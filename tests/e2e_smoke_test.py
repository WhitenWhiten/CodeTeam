# tests/e2e_smoke_test.py
import asyncio
from app.config import SystemConfig
from app.bootstrap import bootstrap
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

def test_e2e_mock(tmp_path):
    cfg = SystemConfig(workspace=str(tmp_path), architects=1)
    cfg.git.enabled = False
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx)
    result = asyncio.run(wf.run(question=cfg.user_question))
    assert result.success, result.reason
    assert result.qa["scope"] == "full"
    assert result.qa["counts"]["passed"] == 4
    assert all(task.done() for task in wf._dev_tasks)
