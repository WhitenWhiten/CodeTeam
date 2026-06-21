from __future__ import annotations
import asyncio
from app.config import load_config
from app.bootstrap import bootstrap
from core.requirements_preprocessor import load_requirements_text, preprocess_requirements
from orchestrator.workflow import MultiAgentCodegenWorkflow
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

def main():
    cfg = load_config()
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx) if cfg.async_mode else MultiAgentCodegenWorkflow(ctx)
    question = load_requirements_text(cfg.requirements_file, cfg.user_question)
    if cfg.preprocess_requirements:
        question = preprocess_requirements(question)
    repo_path = asyncio.run(wf.run(question=question))
    print(f"Done. Repo at: {repo_path}")

if __name__ == "__main__":
    main()
