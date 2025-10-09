# app/bootstrap.py
from core.llm import LLMClient as MockLLM
from core.llm_openai import OpenAILLM
from orchestrator.context import Context

def bootstrap(cfg):
    import os
    os.makedirs(cfg.workspace, exist_ok=True)
    if cfg.llm.provider == "openai":
        llm = OpenAILLM(model=cfg.llm.model, temperature=cfg.llm.temperature, max_tokens=cfg.llm.max_tokens, base_url=cfg.llm.base_url, api_key="sk-Dj3etD6JwITVdH1W8u7DJI63TTw3EBYCvXPQg6KfXSFzHcC1")
    else:
        llm = MockLLM(cfg.llm)
    rag = None  # 可按需初始化
    return Context(cfg=cfg, llm=llm, rag=rag)