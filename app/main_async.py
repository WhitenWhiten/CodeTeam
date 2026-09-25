# app/main_async.py
import asyncio
import json
from core.contracts import to_jsonable
from app.config import load_config
from app.bootstrap import bootstrap
from core.requirements_preprocessor import load_requirements_text, preprocess_requirements
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

async def amain():
    cfg = load_config()
    ctx = bootstrap(cfg)
    wf = MultiAgentCodegenWorkflowAsync(ctx)
    question = load_requirements_text(cfg.requirements_file, cfg.user_question)
    if cfg.preprocess_requirements:
        question = preprocess_requirements(question)
    result = await wf.run(question=question)
    print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
    return 0 if result.success else 1

if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
