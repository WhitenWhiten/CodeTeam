"""Shared, JSON-compatible contracts at workflow boundaries."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, set):
        return [to_jsonable(v) for v in sorted(value)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported contract value: {type(value).__name__}")


def repository_path(value: str) -> str:
    path = value.replace("\\", "/")
    parts = path.split("/")
    if (not path or PurePosixPath(path).is_absolute() or PureWindowsPath(path).drive
            or any(p.casefold() in {"", ".", "..", ".git", ".codeteam_qa"} for p in parts)
            or any(p.endswith((".", " ")) or any(c in p for c in ':<>"|?*') or any(ord(c) < 32 for c in p) for p in parts)
            or any(p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]} for p in parts)):
        raise ValueError(f"Invalid repository-relative path: {value!r}")
    return path


@dataclass
class DeveloperTask:
    file_path: str
    type: Literal["implement", "fix"] = "implement"
    issues: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.file_path = repository_path(self.file_path)
        if self.type not in {"implement", "fix"}:
            raise ValueError(f"Invalid developer task type: {self.type}")


@dataclass
class TestFailure:
    file_path: str = ""
    message: str = ""
    stack: str = ""
    category: str = "test_failure"
    nodeid: str = ""


class RunStatus(str, Enum):
    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"
    CANCELLED = "cancelled"


class BudgetExceeded(RuntimeError):
    """A configured resource ceiling prevented further work."""


class ValidationStopped(RuntimeError):
    """Validation could not converge under the configured repair policy."""


@dataclass
class RunResult:
    status: RunStatus
    repo_root: str | None = None
    stage: str = "created"
    reason: str = ""
    qa: dict[str, Any] | None = None
    artifacts_dir: str | None = None
    repairs: int = 0
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == RunStatus.SUCCESS

    def __fspath__(self) -> str:
        if self.repo_root is None:
            raise ValueError("Run did not create a repository")
        return self.repo_root

    def __str__(self) -> str:
        return self.repo_root or self.status.value
