from core.model_usage import metered_mock
from orchestrator.context import Context
from utils.run_artifacts import RunArtifacts


def bootstrap(cfg):
    import os
    from pathlib import Path

    os.makedirs(cfg.workspace, exist_ok=True)
    provider = (cfg.llm.provider or "mock").lower()
    if provider == "openai":
        from core.llm_openai import OpenAILLM

        llm = OpenAILLM(
            model=cfg.llm.model,
            temperature=cfg.llm.temperature,
            max_tokens=cfg.llm.max_tokens,
            top_p=cfg.llm.top_p,
            base_url=cfg.llm.base_url,
            request_timeout=cfg.llm.request_timeout,
            request_retries=cfg.llm.request_retries,
            token_limit=cfg.max_token_budget,
            call_limit=cfg.max_model_calls,
            seed=cfg.llm.seed,
        )
    elif provider == "mock":
        llm = metered_mock(cfg.llm, cfg.max_token_budget, cfg.max_model_calls)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")

    rag = None
    if cfg.rag.enabled:
        from rag.rag_client import RAGClient

        rag = RAGClient(cfg.rag)

    artifacts_dir = cfg.resume_from or cfg.artifacts_dir
    if cfg.resume_from and not cfg.artifacts_enabled:
        raise ValueError("Resume requires enabled run artifacts")
    if cfg.resume_from and not (Path(cfg.resume_from) / "checkpoint.json").is_file():
        raise ValueError("Resume directory has no checkpoint.json")
    if artifacts_dir and not cfg.resume_from and (Path(artifacts_dir) / "checkpoint.json").exists():
        raise ValueError("Run directory already contains a checkpoint; use resume_from or choose a new directory")
    if not artifacts_dir:
        artifacts = RunArtifacts.create_for_workspace(cfg.workspace, enabled=cfg.artifacts_enabled)
    else:
        artifacts = RunArtifacts(artifacts_dir, enabled=cfg.artifacts_enabled)

    return Context(cfg=cfg, llm=llm, rag=rag, artifacts=artifacts)
