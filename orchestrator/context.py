# orchestrator/context.py
from __future__ import annotations
import time
from uuid import uuid4
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Context:
    cfg: any
    llm: any
    rag: any = None
    artifacts: any = None

    def make_repo_root(self) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        root = Path(self.cfg.workspace).resolve() / f"repo-{ts}-{uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=False)
        return str(root)
