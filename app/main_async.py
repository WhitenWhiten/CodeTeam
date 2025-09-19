# app/main_async.py
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

async def amain():
    cfg = load_config()
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx)
    repo_path = await wf.run(question=cfg.user_question)
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    asyncio.run(amain())
