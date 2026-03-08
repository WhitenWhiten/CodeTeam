from __future__ import annotations
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow import MultiAgentCodegenWorkflow
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

def main():
    cfg = load_config()
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx) if cfg.async_mode else MultiAgentCodegenWorkflow(ctx)
    repo_path = asyncio.run(wf.run(question=cfg.user_question))
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    main()
