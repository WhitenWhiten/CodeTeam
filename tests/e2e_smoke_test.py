# tests/e2e_smoke_test.py
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

def test_e2e_mock():
    cfg = load_config()
    cfg.llm.provider = "mock"
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx)
    repo_path = asyncio.run(wf.run(question=cfg.user_question))
    assert repo_path
    print("Repo at:", repo_path)
