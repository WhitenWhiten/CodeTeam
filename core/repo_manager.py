# core/repo_manager.py
from __future__ import annotations
from git import Repo
from pathlib import Path
from typing import List, Set, Dict
from core.models import RepoNode
from core.schemas import validate_update_reason
import json
import os

class RepoManager:
    def __init__(self, root: str, allowed_files_all: Set[str], allowed_files_by_agent: Dict[str, Set[str]] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = Repo.init(self.root)
        self.allowed_files_all = {self._norm(p) for p in allowed_files_all}
        self.allowed_files_by_agent = {k: {self._norm(p) for p in v} for k, v in (allowed_files_by_agent or {}).items()}

    def _norm(self, file_path: str) -> str:
        return str(Path(file_path).as_posix())

    def exists(self, rel_path: str) -> bool:
        return (self.root / rel_path).exists()

    def init_structure(self, nodes: List[RepoNode]):
        def create(node: RepoNode, base: Path):
            p = base / node.path
            if node.type == "dir":
                p.mkdir(parents=True, exist_ok=True)
                for c in node.children:
                    create(c, p)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")
        for n in nodes:
            create(n, self.root)
        self.commit_all("chore: init repository structure")

    def _assert_allowed(self, rel_path: str):
        norm = self._norm(rel_path)
        if norm not in self.allowed_files_all:
            raise PermissionError(f"Write denied: {norm} not declared in SDS repo_structure")

    def _assert_allowed_by_agent(self, agent_id: str, rel_path: str):
        norm = self._norm(rel_path)
        if agent_id not in self.allowed_files_by_agent:
            raise PermissionError(f"Agent {agent_id} has no write permissions")
        if norm not in self.allowed_files_by_agent[agent_id]:
            raise PermissionError(f"Agent {agent_id} cannot write {norm}")

    def write_file(self, rel_path: str, content: str, agent_id: str | None = None):
        # 全局白名单校验
        self._assert_allowed(rel_path)
        # Agent 级别白名单校验（可选）
        if agent_id:
            self._assert_allowed_by_agent(agent_id, rel_path)
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def commit_file(self, rel_path: str, update_reason: dict, agent_id: str):
        validate_update_reason(update_reason)
        self.repo.index.add([str(self.root / rel_path)])
        msg = f"[{agent_id}] update {rel_path}\nUPDATE_REASON={json.dumps(update_reason, ensure_ascii=False)}"
        self.repo.index.commit(msg)

    def commit_all(self, msg: str):
        # 注意：commit_all 不会绕开权限，只用于结构初始化或 QA 提交测试
        self.repo.git.add(A=True)
        # 若无变更则不提交
        if not self.repo.is_dirty():
            return
        self.repo.index.commit(msg)