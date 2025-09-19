# app/main.py
from __future__ import annotations
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from orchestrator.workflow import MultiAgentCodegenWorkflow

def main():
    cfg = load_config()
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflow(ctx)
    repo_path = asyncio.run(wf.run(question=cfg.user_question))
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    main()
