from __future__ import annotations
import json
import os
from pathlib import Path
from typing import List, Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RAGConfig(ConfigModel):
    enabled: bool = False
    roles: List[Literal['architect', 'cto']] = ['architect']
    index_dir: str = './rag'
    top_k: int = Field(default=5, ge=1)
    corpus_file: Optional[str] = None
    distinct_sources: bool = True
    similarity_threshold: float = Field(default=0.92, gt=0, le=1)
    embedding_model: str = 'BAAI/bge-m3'
    index_backend: Literal['faiss_hnsw', 'lexical'] = 'faiss_hnsw'
    fallback_mode: Literal['lexical', 'error'] = 'lexical'
    chunk_tokens: int = Field(default=768, ge=1)
    chunk_overlap: int = Field(default=128, ge=0)

    @model_validator(mode='after')
    def check_overlap(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError('chunk_overlap must be smaller than chunk_tokens')
        return self


class LLMConfig(ConfigModel):
    provider: str = 'mock'
    model: str = 'Qwen2.5-72B-Instruct'
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=0.95, gt=0, le=1)
    max_tokens: int = Field(default=8192, ge=1)
    base_url: Optional[str] = None
    request_timeout: float = Field(default=60, gt=0)
    request_retries: int = Field(default=2, ge=0, le=10)


class GitConfig(ConfigModel):
    enabled: bool = True


class DeveloperAllocationConfig(ConfigModel):
    dynamic_enabled: bool = True
    fixed_agents: int = Field(default=4, ge=1)
    assignment_seed: Optional[int] = None


class SystemConfig(ConfigModel):
    architects: int = Field(default=4, ge=1)
    architect_seed: Optional[int] = None
    sds_retry: int = Field(default=1, ge=0)
    max_rounds: int = Field(default=2, ge=0)
    max_wall_clock_seconds: Optional[float] = Field(default=None, gt=0)
    max_token_budget: Optional[int] = Field(default=None, ge=0)
    max_model_calls: Optional[int] = Field(default=None, ge=0)
    test_timeout: float = Field(default=120, gt=0)
    python_executable: Optional[str] = None
    workspace: str = './workspace'
    allow_languages: List[str] = ['python']
    user_question: str = 'Build a simplified online shop program with catalog browsing, adding items to a cart, and calculating the checkout total.'
    requirements_file: Optional[str] = None
    preprocess_requirements: bool = True
    artifacts_enabled: bool = True
    artifacts_dir: Optional[str] = None
    resume_from: Optional[str] = None
    async_mode: bool = True
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    developer_allocation: DeveloperAllocationConfig = Field(default_factory=DeveloperAllocationConfig)


ENV_PATHS = {
    'LLM_PROVIDER': 'llm.provider', 'LLM_MODEL': 'llm.model', 'LLM_BASE_URL': 'llm.base_url',
    'LLM_TOP_P': 'llm.top_p', 'LLM_TEMPERATURE': 'llm.temperature', 'LLM_MAX_TOKENS': 'llm.max_tokens',
    'LLM_REQUEST_TIMEOUT': 'llm.request_timeout', 'LLM_REQUEST_RETRIES': 'llm.request_retries',
    'USER_QUESTION': 'user_question', 'REQUIREMENTS_FILE': 'requirements_file',
    'PREPROCESS_REQUIREMENTS': 'preprocess_requirements', 'WORKSPACE': 'workspace',
    'ARCHITECTS': 'architects', 'ARCHITECT_SEED': 'architect_seed', 'SDS_RETRY': 'sds_retry',
    'MAX_QA_ROUNDS': 'max_rounds', 'MAX_WALL_CLOCK_SECONDS': 'max_wall_clock_seconds',
    'MAX_TOKEN_BUDGET': 'max_token_budget', 'MAX_MODEL_CALLS': 'max_model_calls',
    'TEST_TIMEOUT': 'test_timeout', 'PYTHON_EXECUTABLE': 'python_executable', 'ASYNC_MODE': 'async_mode',
    'RAG_ENABLED': 'rag.enabled', 'RAG_CORPUS': 'rag.corpus_file', 'RAG_INDEX_DIR': 'rag.index_dir',
    'RAG_TOP_K': 'rag.top_k', 'RAG_DISTINCT_SOURCES': 'rag.distinct_sources',
    'RAG_SIMILARITY_THRESHOLD': 'rag.similarity_threshold', 'RAG_EMBEDDING_MODEL': 'rag.embedding_model',
    'RAG_BACKEND': 'rag.index_backend', 'RAG_FALLBACK_MODE': 'rag.fallback_mode',
    'RAG_CHUNK_TOKENS': 'rag.chunk_tokens', 'RAG_CHUNK_OVERLAP': 'rag.chunk_overlap',
    'ARTIFACTS_ENABLED': 'artifacts_enabled', 'ARTIFACTS_DIR': 'artifacts_dir',
    'GIT_COLLAB_ENABLED': 'git.enabled', 'DYNAMIC_DEVELOPER_ASSIGNMENT_ENABLED': 'developer_allocation.dynamic_enabled',
    'FIXED_DEVELOPER_AGENTS': 'developer_allocation.fixed_agents',
    'DEVELOPER_ASSIGNMENT_SEED': 'developer_allocation.assignment_seed',
}


def set_config_value(data, path, value):
    parts = path.split('.')
    for key in parts[:-1]:
        data = data.setdefault(key, {})
    data[parts[-1]] = value


def load_config(path: str | None = None, overrides: dict | None = None) -> SystemConfig:
    path = path or os.getenv('CODETEAM_CONFIG')
    data = json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else {}
    if not isinstance(data, dict):
        raise ValueError('Configuration must be a JSON object')
    if os.getenv('OPENAI_BASE_URL'):
        set_config_value(data, 'llm.base_url', os.environ['OPENAI_BASE_URL'])
    for env_name, target in ENV_PATHS.items():
        value = os.getenv('CODETEAM_' + env_name)
        if value is not None:
            set_config_value(data, target, value)
    for target, value in (overrides or {}).items():
        if value is not None:
            set_config_value(data, target, value)
    return SystemConfig.model_validate(data)
