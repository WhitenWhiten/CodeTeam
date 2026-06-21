from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Sequence, Set


def _normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip()


def _is_test_path(path: str) -> bool:
    normalized = _normalize_path(path)
    return normalized.startswith("tests/") or normalized.startswith(".codeteam_qa/tests/")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _iter_file_specs(sds: Any) -> Iterable[Any]:
    return _as_list(_get(sds, "file_specs", []))


def _public_api_names(interfaces: Any) -> Set[str]:
    names: Set[str] = set()
    for func in _as_list(_get(interfaces, "functions", [])):
        name = _get(func, "name", "")
        if name:
            names.add(str(name))
            continue
        signature = _get(func, "signature", "")
        match = re.search(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(signature))
        if match:
            names.add(match.group(1))

    for cls in _as_list(_get(interfaces, "classes", [])):
        name = _get(cls, "name", "")
        if name:
            names.add(str(name))
        for method in _as_list(_get(cls, "methods", [])):
            method_name = _get(method, "name", "")
            if method_name:
                names.add(str(method_name))
    return names


def _build_sds_context(sds: Any) -> Dict[str, Any]:
    specs: Dict[str, Any] = {}
    dependencies: Dict[str, Set[str]] = {}
    dependents: Dict[str, Set[str]] = {}
    public_apis: Dict[str, Set[str]] = {}

    for spec in _iter_file_specs(sds):
        path = _normalize_path(_get(spec, "path", ""))
        if not path:
            continue
        specs[path] = spec
        deps = {_normalize_path(dep) for dep in _as_list(_get(spec, "dependencies", [])) if _normalize_path(dep)}
        dependencies[path] = deps
        public_apis[path] = _public_api_names(_get(spec, "interfaces", {}))
        for dep in deps:
            dependents.setdefault(dep, set()).add(path)

    return {
        "specs": specs,
        "dependencies": dependencies,
        "dependents": dependents,
        "public_apis": public_apis,
    }


def _extract_py_paths(text: str) -> List[str]:
    paths = []
    for match in re.findall(r"([A-Za-z0-9_./\\-]+\.py)", text or ""):
        normalized = _normalize_path(match)
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _paths_from_failure(failure: Mapping[str, Any], src_files: Set[str]) -> Dict[str, Any]:
    explicit_source = _normalize_path(str(failure.get("source_file", "")))
    file_path = _normalize_path(str(failure.get("file_path", "")))
    stack = str(failure.get("stack", "") or failure.get("traceback", "") or "")

    stack_paths = _extract_py_paths(stack)
    source_paths = []
    test_paths = []
    for path in [explicit_source, file_path, *stack_paths]:
        if not path:
            continue
        if path in src_files and path not in source_paths:
            source_paths.append(path)
        elif _is_test_path(path) and path not in test_paths:
            test_paths.append(path)

    return {
        "explicit_source": explicit_source if explicit_source in src_files else "",
        "file_path": file_path,
        "source_paths": source_paths,
        "test_paths": test_paths,
        "stack_paths": stack_paths,
    }


def _extract_missing_symbol(text: str) -> str:
    patterns = [
        r"cannot import name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"ImportError:\s+cannot import name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"AttributeError:\s+module ['\"][^'\"]+['\"] has no attribute ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"AttributeError:\s+['\"][^'\"]+['\"] object has no attribute ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
        r"NameError:\s+name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def _extract_import_module(text: str) -> str:
    patterns = [
        r"from\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+import\s+[A-Za-z_][A-Za-z0-9_]*",
        r"No module named ['\"]([A-Za-z_][A-Za-z0-9_\.]*)['\"]",
        r"ModuleNotFoundError:\s+No module named ['\"]([A-Za-z_][A-Za-z0-9_\.]*)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def _module_to_candidate_files(module_name: str, src_files: Set[str]) -> List[str]:
    if not module_name:
        return []
    module_path = module_name.replace(".", "/")
    candidates = [
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    ]
    tail_candidates = [
        source_file
        for source_file in src_files
        if source_file.endswith(f"/{module_path}.py") or source_file == f"{module_path}.py"
    ]
    ordered = []
    for candidate in [*candidates, *tail_candidates]:
        if candidate in src_files and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _source_for_public_api(symbol: str, public_apis: Mapping[str, Set[str]]) -> List[str]:
    if not symbol:
        return []
    return [path for path, names in public_apis.items() if symbol in names]


def _dependent_paths_for_failure(path_info: Mapping[str, Any], dependencies: Mapping[str, Set[str]]) -> List[str]:
    ordered = []
    for path in path_info.get("source_paths", []):
        if path not in ordered:
            ordered.append(path)
    return [path for path in ordered if path in dependencies]


def _choose_source_path(
    failure: Mapping[str, Any],
    src_files: Set[str],
    sds_ctx: Mapping[str, Any],
    path_info: Mapping[str, Any],
) -> Dict[str, Any]:
    stack = str(failure.get("stack", "") or failure.get("traceback", "") or "")
    message = str(failure.get("message", ""))
    text = "\n".join([message, stack])
    public_apis: Mapping[str, Set[str]] = sds_ctx["public_apis"]
    dependencies: Mapping[str, Set[str]] = sds_ctx["dependencies"]

    missing_symbol = _extract_missing_symbol(text)
    import_module = _extract_import_module(text)
    imported_files = _module_to_candidate_files(import_module, src_files)
    api_sources = _source_for_public_api(missing_symbol, public_apis)
    dependent_paths = _dependent_paths_for_failure(path_info, dependencies)

    diagnostics = {
        "interface_consistency": {
            "status": "not_evaluated",
            "symbol": missing_symbol,
            "candidate_sources": [],
        },
        "dependency_directionality": {
            "status": "not_evaluated",
            "dependent_files": dependent_paths,
            "provider_files": [],
        },
        "structural_validity": {
            "status": "valid" if path_info.get("source_paths") or path_info.get("test_paths") else "unknown",
            "source_paths_in_trace": path_info.get("source_paths", []),
            "test_paths_in_trace": path_info.get("test_paths", []),
        },
        "minimal_repair_scope": {
            "status": "unknown",
            "files": [],
        },
    }

    if missing_symbol and (imported_files or api_sources):
        provider_files = imported_files or api_sources
        if imported_files and api_sources:
            provider_files = [path for path in imported_files if path in api_sources] or imported_files
        provider_files = [path for path in provider_files if path in src_files]

        diagnostics["interface_consistency"] = {
            "status": "missing_or_mismatched_public_api",
            "symbol": missing_symbol,
            "candidate_sources": provider_files,
        }
        diagnostics["dependency_directionality"] = {
            "status": "provider_selected_from_import_or_public_api",
            "dependent_files": dependent_paths,
            "provider_files": provider_files,
        }
        if provider_files:
            return {
                "category": "interface_consistency",
                "targets": provider_files[:1],
                "diagnostics": diagnostics,
                "public_api_changed": True,
            }

    if path_info.get("explicit_source"):
        target = path_info["explicit_source"]
        diagnostics["minimal_repair_scope"] = {"status": "explicit_source_file", "files": [target]}
        return {
            "category": "structural_validity",
            "targets": [target],
            "diagnostics": diagnostics,
            "public_api_changed": False,
        }

    for path in reversed(path_info.get("source_paths", [])):
        if path in src_files:
            diagnostics["minimal_repair_scope"] = {"status": "nearest_source_traceback_frame", "files": [path]}
            return {
                "category": "minimal_repair_scope",
                "targets": [path],
                "diagnostics": diagnostics,
                "public_api_changed": False,
            }

    diagnostics["minimal_repair_scope"] = {"status": "unknown", "files": []}
    return {
        "category": "unknown",
        "targets": [],
        "diagnostics": diagnostics,
        "public_api_changed": False,
    }


def _affected_dependents(targets: Sequence[str], dependents: Mapping[str, Set[str]]) -> List[str]:
    affected: Set[str] = set()
    for target in targets:
        affected.update(dependents.get(target, set()))
    return sorted(affected)


def _primary_issue_text(failure: Mapping[str, Any]) -> str:
    message = str(failure.get("message", "") or "").strip()
    if message:
        return message
    stack = str(failure.get("stack", "") or "")
    for line in stack.splitlines():
        if line.strip():
            return line.strip()
    return "test failure"


def build_fix_suggestions(
    failures: List[Dict[str, Any]],
    file_owner: Dict[str, str],
    sds: Any = None,
) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    seen: Set[tuple[str, str, str]] = set()
    src_files: Set[str] = set(file_owner.keys())
    sds_ctx = _build_sds_context(sds)

    for failure in failures:
        path_info = _paths_from_failure(failure, src_files)
        route = _choose_source_path(failure, src_files, sds_ctx, path_info)
        targets = [target for target in route["targets"] if target in file_owner]
        affected = _affected_dependents(targets, sds_ctx["dependents"])
        issue_text = _primary_issue_text(failure)

        if not targets:
            key = ("", "", issue_text)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                {
                    "dev_id": None,
                    "file_path": "",
                    "issues": failure,
                    "category": "unknown",
                    "suspected_source_files": [],
                    "minimal_repair_scope": [],
                    "public_api_changed": False,
                    "affected_dependents": [],
                    "diagnostics": route["diagnostics"],
                    "requeue": False,
                }
            )
            continue

        for file_path in targets:
            key = (file_owner[file_path], file_path, issue_text)
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                {
                    "dev_id": file_owner[file_path],
                    "file_path": file_path,
                    "issues": failure,
                    "category": route["category"],
                    "suspected_source_files": targets,
                    "minimal_repair_scope": [file_path],
                    "public_api_changed": route["public_api_changed"],
                    "affected_dependents": affected,
                    "diagnostics": route["diagnostics"],
                    "requeue": True,
                }
            )
    return suggestions
