from __future__ import annotations
import asyncio
import sys
import json
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.bootstrap import bootstrap
from core.contracts import to_jsonable
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
    result = asyncio.run(wf.run(question=question))
    print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
    return 0 if result.success else 1

if __name__ == "__main__":
    raise SystemExit(main())
