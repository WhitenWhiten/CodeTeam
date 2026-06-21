from core.llm import LLMClient as MockLLM
from orchestrator.context import Context
from utils.run_artifacts import RunArtifacts


def bootstrap(cfg):
    import os

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
        )
    else:
        llm = MockLLM(cfg.llm)

    rag = None
    if cfg.rag.enabled:
        from rag.rag_client import RAGClient

        rag = RAGClient(cfg.rag)

    artifacts_dir = cfg.artifacts_dir
    if not artifacts_dir:
        artifacts = RunArtifacts.create_for_workspace(cfg.workspace, enabled=cfg.artifacts_enabled)
    else:
        artifacts = RunArtifacts(artifacts_dir, enabled=cfg.artifacts_enabled)

    return Context(cfg=cfg, llm=llm, rag=rag, artifacts=artifacts)
