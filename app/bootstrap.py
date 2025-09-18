import os
from core.llm import LLMClient
from rag.rag_client import RAGClient
from orchestrator.context import Context

def bootstrap(cfg):
    os.makedirs(cfg.workspace, exist_ok=True)
    llm = LLMClient(cfg.llm)
    rag = RAGClient(cfg.rag) if cfg.rag.enabled else None
    ctx = Context(cfg=cfg, llm=llm, rag=rag)
    return ctx