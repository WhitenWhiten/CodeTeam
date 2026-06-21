from core.llm import LLMClient as MockLLM
from orchestrator.context import Context


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
        try:
            from rag.rag_client import RAGClient

            rag = RAGClient(cfg.rag)
        except Exception:
            rag = None

    return Context(cfg=cfg, llm=llm, rag=rag)
