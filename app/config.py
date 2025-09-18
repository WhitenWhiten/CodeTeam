from pydantic import BaseModel, Field, validator
from typing import List, Optional

class RAGConfig(BaseModel):
    enabled: bool = True
    index_dir: str
    top_k: int = 6

class LLMConfig(BaseModel):
    model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4000

class SystemConfig(BaseModel):
    architects: int = 3
    sds_retry: int = 2
    max_rounds: int = 5
    workspace: str = "./workspace"
    allow_languages: List[str] = ["python"]
    user_question: str

    llm: LLMConfig
    rag: RAGConfig

def load_config(path: str = None) -> SystemConfig:
    # 读取 YAML/ENV 并返回
    ...