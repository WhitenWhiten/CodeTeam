from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List


def normalize_sds_candidates(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_sds_candidate(candidate) for candidate in candidates]


def normalize_sds_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonical SDS dict while accepting paper-era field aliases."""
    if not isinstance(candidate, dict):
        return candidate

    normalized = deepcopy(candidate)
    _move_alias(normalized, "repo_tree", "repo_structure")
    _move_alias(normalized, "files", "file_specs")
    _move_alias(normalized, "developer_plan", "dev_plan")

    if "repo_structure" in normalized:
        normalized["repo_structure"] = _normalize_repo_structure(normalized["repo_structure"])

    file_specs = normalized.get("file_specs")
    if isinstance(file_specs, dict):
        file_specs = [
            {**(spec if isinstance(spec, dict) else {"responsibilities": str(spec)}), "path": _normalize_path(path)}
            for path, spec in file_specs.items()
        ]
    if isinstance(file_specs, list):
        normalized["file_specs"] = [_normalize_file_spec(fs) for fs in file_specs]

    if "dev_plan" in normalized:
        normalized["dev_plan"] = _normalize_dev_plan(normalized.get("dev_plan"))
    else:
        normalized["dev_plan"] = _dev_plan_from_file_owners(normalized.get("file_specs", []))

    _apply_owner_mapping(normalized.get("file_specs", []), normalized.get("dev_plan", []))
    return normalized


def _move_alias(payload: Dict[str, Any], alias: str, canonical: str) -> None:
    alias_value = payload.pop(alias, None)
    if canonical not in payload and alias_value is not None:
        payload[canonical] = alias_value


def _normalize_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    path = value.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def _normalize_repo_structure(repo_structure: Any) -> Any:
    if isinstance(repo_structure, list):
        if all(isinstance(item, str) for item in repo_structure):
            return _paths_to_repo_nodes(repo_structure)
        return [_normalize_repo_node(item) for item in repo_structure]
    if isinstance(repo_structure, dict):
        return _dict_tree_to_repo_nodes(repo_structure)
    return repo_structure


def _normalize_repo_node(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    normalized = deepcopy(node)
    if "path" in normalized:
        normalized["path"] = _normalize_path(normalized["path"])
    if normalized.get("type") == "dir":
        normalized["children"] = [_normalize_repo_node(child) for child in normalized.get("children", [])]
    return normalized


def _paths_to_repo_nodes(paths: Iterable[str]) -> List[Dict[str, Any]]:
    root: Dict[str, Any] = {}
    for raw_path in paths:
        path = _normalize_path(raw_path)
        if not path:
            continue
        cursor = root
        parts = path.split("/")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor.setdefault(parts[-1], None)
    return _dict_tree_to_repo_nodes(root)


def _dict_tree_to_repo_nodes(tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for name, value in tree.items():
        path = _normalize_path(name)
        if isinstance(value, dict):
            nodes.append({"path": path, "type": "dir", "children": _dict_tree_to_repo_nodes(value)})
        else:
            nodes.append({"path": path, "type": "file"})
    return nodes


def _normalize_file_spec(file_spec: Any) -> Any:
    if not isinstance(file_spec, dict):
        return file_spec

    normalized = deepcopy(file_spec)
    _move_alias(normalized, "public_api", "interfaces")
    _move_alias(normalized, "responsibility", "responsibilities")
    _move_alias(normalized, "purpose", "responsibilities")
    _move_alias(normalized, "description", "responsibilities")

    if "path" in normalized:
        normalized["path"] = _normalize_path(normalized["path"])
    if "responsibilities" not in normalized:
        normalized["responsibilities"] = ""

    if "interfaces" in normalized:
        normalized["interfaces"] = _normalize_interfaces(normalized["interfaces"])

    deps = []
    if "dependencies" in normalized:
        deps.extend(_normalize_dependency_list(normalized.get("dependencies")))
    if "depends_on" in normalized:
        deps.extend(_normalize_dependency_list(normalized.pop("depends_on")))
    if deps or "dependencies" in normalized:
        normalized["dependencies"] = _unique_strings(deps)

    if "owner" in normalized and normalized["owner"] is not None:
        normalized["owner"] = str(normalized["owner"]).strip()
    return normalized


def _normalize_interfaces(interfaces: Any) -> Any:
    if isinstance(interfaces, list):
        return {"functions": [_function_from_string(item) for item in interfaces if isinstance(item, str)], "classes": []}
    if not isinstance(interfaces, dict):
        return interfaces
    normalized = deepcopy(interfaces)
    normalized.setdefault("functions", [])
    normalized.setdefault("classes", [])
    return normalized


def _function_from_string(value: str) -> Dict[str, str]:
    name = value.strip().split("(", 1)[0].replace("def ", "").strip()
    return {"name": name, "signature": value.strip()}


def _normalize_dependency_list(dependencies: Any) -> List[str]:
    if dependencies is None:
        return []
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    if not isinstance(dependencies, list):
        return []

    normalized: List[str] = []
    for dependency in dependencies:
        value = _normalize_dependency(dependency)
        if isinstance(value, str) and value:
            normalized.append(value)
    return normalized


def _normalize_dependency(dependency: Any) -> Any:
    if isinstance(dependency, str):
        value = dependency.strip()
        if "::" in value:
            file_part, symbol_part = value.split("::", 1)
            return f"{_normalize_path(file_part)}::{symbol_part.strip()}"
        return _normalize_path(value) if ("/" in value or "\\" in value) else value
    if isinstance(dependency, dict):
        file_ref = dependency.get("path") or dependency.get("file_path") or dependency.get("file")
        symbol_ref = dependency.get("symbol") or dependency.get("name")
        if file_ref and symbol_ref:
            return f"{_normalize_dependency(file_ref)}:{_normalize_dependency(symbol_ref)}"
        for key in ("path", "file_path", "file", "symbol", "name", "ref"):
            if key in dependency:
                return _normalize_dependency(dependency[key])
    return dependency


def _normalize_dev_plan(dev_plan: Any) -> Any:
    if isinstance(dev_plan, dict):
        if isinstance(dev_plan.get("owners"), list):
            dev_plan = dev_plan["owners"]
        else:
            dev_plan = [
                {"developer_id": developer_id, "file_paths": file_paths}
                for developer_id, file_paths in dev_plan.items()
            ]
    if not isinstance(dev_plan, list):
        return dev_plan
    normalized = []
    for assignment in dev_plan:
        if not isinstance(assignment, dict):
            normalized.append(assignment)
            continue
        item = deepcopy(assignment)
        developer_id = item.get("developer_id")
        if developer_id is None:
            developer_id = item.get("id")
        if developer_id is None:
            developer_id = item.get("name") or item.get("owner")
        file_paths = item.get("file_paths")
        if file_paths is None:
            file_paths = item.get("files") or item.get("paths") or item.get("owns")
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        if isinstance(file_paths, list):
            file_paths = [_normalize_path(path) for path in file_paths]
        if developer_id is not None:
            developer_id = str(developer_id).strip()
        normalized.append({"developer_id": developer_id, "file_paths": file_paths})
    return normalized


def _dev_plan_from_file_owners(file_specs: Any) -> List[Dict[str, Any]]:
    if not isinstance(file_specs, list):
        return []
    owner_to_paths: Dict[str, List[str]] = {}
    for file_spec in file_specs:
        if not isinstance(file_spec, dict):
            continue
        owner = file_spec.get("owner")
        path = file_spec.get("path")
        if owner is not None and isinstance(path, str) and path:
            owner_id = str(owner).strip()
            if owner_id:
                owner_to_paths.setdefault(owner_id, []).append(path)
    return [{"developer_id": owner, "file_paths": paths} for owner, paths in owner_to_paths.items()]


def _apply_owner_mapping(file_specs: Any, dev_plan: Any) -> None:
    if not isinstance(file_specs, list) or not isinstance(dev_plan, list):
        return
    owner_by_path: Dict[str, str] = {}
    for assignment in dev_plan:
        if not isinstance(assignment, dict):
            continue
        developer_id = assignment.get("developer_id")
        if developer_id is None:
            continue
        developer_id = str(developer_id).strip()
        for path in assignment.get("file_paths") or []:
            if isinstance(path, str):
                owner_by_path[_normalize_path(path)] = developer_id
    for file_spec in file_specs:
        if not isinstance(file_spec, dict):
            continue
        path = file_spec.get("path")
        if isinstance(path, str) and not file_spec.get("owner") and path in owner_by_path:
            file_spec["owner"] = owner_by_path[path]


def _unique_strings(values: Iterable[str]) -> List[str]:
    seen = set()
    unique = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
