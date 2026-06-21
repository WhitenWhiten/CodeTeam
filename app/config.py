# app/config.py
from __future__ import annotations
import os
from pydantic import BaseModel
from typing import List, Optional


class RAGConfig(BaseModel):
    enabled: bool = False
    index_dir: str = "./rag"
    top_k: int = 5
    corpus_file: Optional[str] = None


class LLMConfig(BaseModel):
    provider: str = "mock"   # mock|openai
    model: str = "Qwen2.5-72B-Instruct"
    temperature: float = 0.2
    top_p: float = 0.95
    max_tokens: int = 8192
    base_url: Optional[str] = "https://api.openai-proxy.org/v1"


class GitConfig(BaseModel):
    enabled: bool = True


class DeveloperAllocationConfig(BaseModel):
    dynamic_enabled: bool = True
    fixed_agents: int = 4
    assignment_seed: Optional[int] = None


class SystemConfig(BaseModel):
    architects: int = 4
    sds_retry: int = 1
    max_rounds: int = 2
    max_wall_clock_seconds: Optional[int] = None
    max_token_budget: Optional[int] = None
    workspace: str = "./workspace"
    allow_languages: List[str] = ["python"]
    user_question: str = "生成一个简化版 online shop 程序，包含商品浏览、加入购物车和结算总价三个核心能力"
    requirements_file: Optional[str] = None
    preprocess_requirements: bool = True
    async_mode: bool = True
    llm: LLMConfig = LLMConfig()
    rag: RAGConfig = RAGConfig()
    git: GitConfig = GitConfig()
    developer_allocation: DeveloperAllocationConfig = DeveloperAllocationConfig()


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def load_config(path: str = None) -> SystemConfig:
    # 简化：使用默认配置，并支持少量环境变量覆盖
    cfg = SystemConfig()

    provider = os.getenv("CODETEAM_LLM_PROVIDER")
    if provider:
        cfg.llm.provider = provider

    model = os.getenv("CODETEAM_LLM_MODEL")
    if model:
        cfg.llm.model = model

    top_p = os.getenv("CODETEAM_LLM_TOP_P")
    if top_p:
        cfg.llm.top_p = float(top_p)

    max_tokens = os.getenv("CODETEAM_LLM_MAX_TOKENS")
    if max_tokens:
        cfg.llm.max_tokens = int(max_tokens)

    question = os.getenv("CODETEAM_USER_QUESTION")
    if question:
        cfg.user_question = question

    requirements_file = os.getenv("CODETEAM_REQUIREMENTS_FILE")
    if requirements_file:
        cfg.requirements_file = requirements_file

    preprocess_requirements = os.getenv("CODETEAM_PREPROCESS_REQUIREMENTS")
    if preprocess_requirements is not None:
        cfg.preprocess_requirements = _parse_bool(preprocess_requirements)

    workspace = os.getenv("CODETEAM_WORKSPACE")
    if workspace:
        cfg.workspace = workspace

    architects = os.getenv("CODETEAM_ARCHITECTS")
    if architects:
        cfg.architects = max(1, int(architects))

    max_rounds = os.getenv("CODETEAM_MAX_QA_ROUNDS")
    if max_rounds:
        cfg.max_rounds = max(0, int(max_rounds))

    max_wall_clock = os.getenv("CODETEAM_MAX_WALL_CLOCK_SECONDS")
    if max_wall_clock:
        cfg.max_wall_clock_seconds = max(1, int(max_wall_clock))

    max_token_budget = os.getenv("CODETEAM_MAX_TOKEN_BUDGET")
    if max_token_budget:
        cfg.max_token_budget = max(1, int(max_token_budget))

    async_mode = os.getenv("CODETEAM_ASYNC_MODE")
    if async_mode is not None:
        cfg.async_mode = _parse_bool(async_mode)

    rag_enabled = os.getenv("CODETEAM_RAG_ENABLED")
    if rag_enabled is not None:
        cfg.rag.enabled = _parse_bool(rag_enabled)

    corpus_file = os.getenv("CODETEAM_RAG_CORPUS")
    if corpus_file:
        cfg.rag.corpus_file = corpus_file

    rag_top_k = os.getenv("CODETEAM_RAG_TOP_K")
    if rag_top_k:
        cfg.rag.top_k = max(1, int(rag_top_k))

    git_enabled = os.getenv("CODETEAM_GIT_COLLAB_ENABLED")
    if git_enabled is not None:
        cfg.git.enabled = _parse_bool(git_enabled)

    dynamic_dev = os.getenv("CODETEAM_DYNAMIC_DEVELOPER_ASSIGNMENT_ENABLED")
    if dynamic_dev is not None:
        cfg.developer_allocation.dynamic_enabled = _parse_bool(dynamic_dev)

    fixed_agents = os.getenv("CODETEAM_FIXED_DEVELOPER_AGENTS")
    if fixed_agents:
        cfg.developer_allocation.fixed_agents = max(1, int(fixed_agents))

    assignment_seed = os.getenv("CODETEAM_DEVELOPER_ASSIGNMENT_SEED")
    if assignment_seed:
        cfg.developer_allocation.assignment_seed = int(assignment_seed)

    return cfg
