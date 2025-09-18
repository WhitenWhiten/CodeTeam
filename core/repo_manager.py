from git import Repo
from pathlib import Path
from typing import List, Set
from core.models import RepoNode
from core.schemas import validate_update_reason
import json

class RepoManager:
    def __init__(self, root: str, allowed_files: Set[str]):
        self.root = Path(root)
        self.repo = Repo.init(self.root)
        self.allowed_files = allowed_files

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
                    p.write_text("")
        for n in nodes:
            create(n, self.root)
        self.commit_all("chore: init repository structure")

    def _assert_allowed(self, file_path: str):
        norm = str(Path(file_path).as_posix())
        if norm not in self.allowed_files:
            raise PermissionError(f"Write denied: {norm} not in SDS plan")

    def write_file(self, rel_path: str, content: str):
        self._assert_allowed(rel_path)
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def commit_file(self, rel_path: str, update_reason: dict, agent_id: str):
        validate_update_reason(update_reason)
        self.repo.index.add([str(self.root / rel_path)])
        msg = f"[{agent_id}] update {rel_path}\nUPDATE_REASON={json.dumps(update_reason, ensure_ascii=False)}"
        self.repo.index.commit(msg)

    def commit_all(self, msg: str):
        self.repo.git.add(A=True)
        self.repo.index.commit(msg)