from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any


class RunArtifacts:
    def __init__(self, base_dir: str | None, enabled: bool = True):
        self.enabled = enabled and bool(base_dir)
        self.root = Path(base_dir).resolve() if self.enabled else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create_for_workspace(cls, workspace: str, run_id: str | None = None, enabled: bool = True) -> "RunArtifacts":
        run_name = run_id or time.strftime("run-%Y%m%d-%H%M%S")
        return cls(str(Path(workspace) / "run_artifacts" / run_name), enabled=enabled)

    def write_json(self, relative_path: str, payload: Any) -> None:
        if not self.root:
            return
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def write_text(self, relative_path: str, text: str) -> None:
        if not self.root:
            return
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")

    def copy_file(self, source: str, relative_path: str) -> None:
        if not self.root:
            return
        src = Path(source)
        if not src.exists() or not src.is_file():
            return
        dst = self.root / relative_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v) for v in value)
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
