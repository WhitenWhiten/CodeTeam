# orchestrator/context.py
from __future__ import annotations
import time
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Context:
    cfg: any
    llm: any
    rag: any = None

    def make_repo_root(self) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        root = Path(self.cfg.workspace) / f"repo-{ts}"
        root.mkdir(parents=True, exist_ok=True)
        return str(root)