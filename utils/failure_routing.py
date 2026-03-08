from __future__ import annotations

from typing import Any, Dict, List, Set


def _normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip()


def _find_target_source(failure: Dict[str, Any], src_files: Set[str]) -> str | None:
    explicit_paths = [
        _normalize_path(failure.get("source_file", "")),
        _normalize_path(failure.get("file_path", "")),
    ]
    for candidate in explicit_paths:
        if candidate in src_files:
            return candidate

    stack = failure.get("stack", "") or ""
    for line in stack.splitlines():
        for source_file in src_files:
            if source_file in line:
                return source_file
    return None


def build_fix_suggestions(
    failures: List[Dict[str, Any]],
    file_owner: Dict[str, str],
) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    seen: Set[tuple[str, str, str]] = set()
    src_files: Set[str] = set(file_owner.keys())

    for failure in failures:
        target = _find_target_source(failure, src_files)
        target_files = [target] if target else sorted(src_files)
        for file_path in target_files:
            key = (
                file_owner[file_path],
                file_path,
                str(failure.get("message", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                {
                    "dev_id": file_owner[file_path],
                    "file_path": file_path,
                    "issues": failure,
                }
            )
    return suggestions
