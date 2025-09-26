# app/config.py
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional

class RAGConfig(BaseModel):
    enabled: bool = False
    index_dir: str = "./rag_index"
    top_k: int = 6

class LLMConfig(BaseModel):
    provider: str = "openai"   # mock|openai
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.2
    max_tokens: int = 4000
    base_url: Optional[str] = None

class SystemConfig(BaseModel):
    architects: int = 2
    sds_retry: int = 1
    max_rounds: int = 2
    workspace: str = "./workspace"
    allow_languages: List[str] = ["python"]
    user_question: str = "请生成一个简单的可测试问候程序"
    async_mode: bool = True
    llm: LLMConfig = LLMConfig()
    rag: RAGConfig = RAGConfig()


def load_config(path: str = None) -> SystemConfig:
    # 简化：使用默认配置；可扩展读取 YAML/ENV
    return SystemConfig()
