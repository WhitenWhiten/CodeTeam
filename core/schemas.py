# core/schemas.py
from __future__ import annotations
from typing import Dict, Any, List, Set, Tuple
from utils.sds_normalizer import normalize_sds_candidate
try:
    import jsonschema
except ImportError:
    jsonschema = None

# 基础结构 Schema
SDS_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "required": ["id", "problem", "tech_stack", "repo_structure", "file_specs", "dev_plan"],
  "properties": {
    "id": {"type": "string"},
    "problem": {"type": "string", "minLength": 1},
    "tech_stack": {
      "type": "object",
      "required": ["language", "frameworks", "runtime", "test_framework"],
      "properties": {
        "language": {"type": "string"},
        "frameworks": {"type": "array", "items": {"type": "string"}},
        "runtime": {"type": "string"},
        "test_framework": {"type": "string"}
      },
      "additionalProperties": True
    },
    "repo_structure": {
      "type": "array",
      "minItems": 1,
      "items": {"$ref": "#/$defs/RepoNode"}
    },
    "file_specs": {
      "type": "array",
      "minItems": 1,
      "items": {"$ref": "#/$defs/FileSpec"}
    },
    "dev_plan": {
      "type": "array",
      "minItems": 1,
      "items": {"$ref": "#/$defs/DevAssignment"}
    },
    "dependencies": {"type": "array", "items": {"type": "string"}},
    "constraints": {"type": "object"},
    "notes": {"type": "string"}
  },
  "$defs": {
    "RepoNode": {
      "type": "object",
      "required": ["path", "type"],
      "properties": {
        "path": {
          "type": "string",
          "pattern": r"^(?!/)(?!.*\.\.)(?!.*//)[\w\-.~/]+$"  # 防止绝对路径、..、重复//
        },
        "type": {"type": "string", "enum": ["file", "dir"]},
        "children": {
          "type": "array",
          "items": {"$ref": "#/$defs/RepoNode"},
          "default": []
        }
      },
      "additionalProperties": False
    },
    "FuncBrief": {
      "type": "object",
      "required": ["name", "signature"],
      "properties": {
        "name": {"type": "string"},
        "signature": {"type": "string"},
        "doc": {"type": "string"}
      },
      "additionalProperties": False
    },
    "ClassBrief": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "init_signature": {"type": "string"},
        "methods": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
        "doc": {"type": "string"}
      },
      "additionalProperties": False
    },
    "FileSpec": {
      "type": "object",
      "required": ["path", "responsibilities", "interfaces"],
      "properties": {
        "path": {"type": "string"},
        "responsibilities": {"type": "string"},
        "interfaces": {
          "type": "object",
          "required": ["functions", "classes"],
          "properties": {
            "functions": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}},
            "classes": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}}
          },
          "additionalProperties": False
        },
        "dependencies": {"type": "array", "items": {"type": "string"}, "default": []}
        ,
        "owner": {"type": "string"}
      },
      "additionalProperties": False
    },
    "DevAssignment": {
      "type": "object",
      "required": ["developer_id", "file_paths"],
      "properties": {
        "developer_id": {"type": "string"},
        "file_paths": {
          "type": "array",
          "minItems": 1,
          "items": {"type": "string"},
          "uniqueItems": True
        }
      },
      "additionalProperties": False
    }
  },
  "additionalProperties": False
}

UPDATE_REASON_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "required": [
    "target_file",
    "file_path",
    "change_type",
    "rationale",
    "related_files_brief_used",
    "modified_exported_symbols",
    "compatibility_note",
    "affected_dependent_files",
  ],
  "properties": {
    "target_file": {"type": "string"},
    "file_path": {"type": "string"},
    "change_type": {"type": "string", "enum": ["create", "modify"]},
    "functions_added": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "functions_modified": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "functions_removed": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "classes_added": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
    "classes_modified": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
    "classes_removed": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
    "modified_exported_symbols": {"type": "array", "items": {"type": "string"}, "default": []},
    "compatibility_note": {"type": "string"},
    "affected_dependent_files": {"type": "array", "items": {"type": "string"}, "default": []},
    "rationale": {"type": "string"},
    "related_files_brief_used": {"type": "array", "items": {"type": "string"}},
  },
  "$defs": {
    "FuncBrief": SDS_SCHEMA["$defs"]["FuncBrief"],
    "ClassBrief": SDS_SCHEMA["$defs"]["ClassBrief"]
  },
  "additionalProperties": False
}

QA_TEST_BUNDLE_SCHEMA: Dict[str, Any] = {
  "type": "object",
  "required": ["tests", "run_command"],
  "properties": {
    "tests": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {"type": "string"}
    },
    "run_command": {"type": "string", "minLength": 1},
    "setup_commands": {
      "type": "array",
      "items": {"type": "string"},
      "default": []
    }
  },
  "additionalProperties": False
}

def _jsonschema_validate(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    if jsonschema is not None:
        jsonschema.validate(payload, schema)

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def validate_sds_structure(sds_json: Dict[str, Any]) -> None:
    sds_json = normalize_sds_candidate(sds_json)
    _jsonschema_validate(sds_json, SDS_SCHEMA)
    _require(isinstance(sds_json, dict), "SDS must be an object")
    for key in ("id", "problem", "tech_stack", "repo_structure", "file_specs", "dev_plan"):
        _require(key in sds_json, f"missing SDS field: {key}")
    _require(isinstance(sds_json["repo_structure"], list) and sds_json["repo_structure"], "repo_structure must be a non-empty list")
    _require(isinstance(sds_json["file_specs"], list) and sds_json["file_specs"], "file_specs must be a non-empty list")
    _require(isinstance(sds_json["dev_plan"], list) and sds_json["dev_plan"], "dev_plan must be a non-empty list")

def _flatten_repo_file_list(nodes) -> List[str]:
    files: List[str] = []
    def walk(n, base=""):
        p = f"{base}/{n['path']}".lstrip("/")
        if n["type"] == "file":
            files.append(p)
        else:
            for c in n.get("children", []):
                walk(c, p)
    for node in nodes:
        walk(node, "")
    return files

def _flatten_repo_files(nodes) -> Set[str]:
    return set(_flatten_repo_file_list(nodes))

def _module_name(path: str) -> str:
    if path.endswith(".py"):
        path = path[:-3]
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    return path.replace("/", ".")

def _signature_name(signature: str) -> str:
    text = signature.strip()
    if text.startswith("def "):
        text = text[4:]
    return text.split("(", 1)[0].strip()

def _collect_declared_symbols(file_specs: List[Dict[str, Any]]) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    symbol_to_files: Dict[str, Set[str]] = {}
    file_symbols: Dict[str, Set[str]] = {}

    def add_symbol(path: str, symbol: str) -> None:
        if not symbol:
            return
        module = _module_name(path)
        aliases = {symbol, f"{path}:{symbol}", f"{path}#{symbol}"}
        if module:
            aliases.add(f"{module}.{symbol}")
        file_symbols.setdefault(path, set()).add(symbol)
        for alias in aliases:
            symbol_to_files.setdefault(alias, set()).add(path)

    for fs in file_specs:
        path = fs["path"]
        interfaces = fs.get("interfaces") or {}
        for func in interfaces.get("functions") or []:
            name = func.get("name") or _signature_name(func.get("signature", ""))
            add_symbol(path, name)
        for cls in interfaces.get("classes") or []:
            class_name = cls.get("name", "")
            add_symbol(path, class_name)
            for method in cls.get("methods") or []:
                method_name = method.get("name") or _signature_name(method.get("signature", ""))
                add_symbol(path, method_name)
                add_symbol(path, f"{class_name}.{method_name}")
    return symbol_to_files, file_symbols

def _normalize_dependency_ref(value: str) -> str:
    ref = value.replace("\\", "/").strip()
    while ref.startswith("./"):
        ref = ref[2:]
    return ref.strip("/")

def _resolve_dependency_targets(
    dependency: str,
    repo_files: Set[str],
    spec_set: Set[str],
    symbol_to_files: Dict[str, Set[str]],
    file_symbols: Dict[str, Set[str]],
) -> Tuple[bool, Set[str]]:
    ref = _normalize_dependency_ref(dependency)
    if not ref:
        return False, set()

    if ref in repo_files:
        return True, {ref} if ref in spec_set else set()

    if ref in symbol_to_files:
        return True, set(symbol_to_files[ref])

    callable_name = ref.split("(", 1)[0].strip()
    if callable_name in symbol_to_files:
        return True, set(symbol_to_files[callable_name])

    for sep in ("::", ":", "#"):
        if sep in ref:
            file_part, symbol_part = ref.split(sep, 1)
            file_part = _normalize_dependency_ref(file_part)
            symbol_part = symbol_part.strip().split("(", 1)[0]
            if file_part not in repo_files:
                return False, set()
            if not symbol_part or symbol_part in file_symbols.get(file_part, set()):
                return True, {file_part} if file_part in spec_set else set()
            return False, set()

    if "." in ref and "/" not in ref and not ref.endswith(".py"):
        module_part, symbol_part = ref.rsplit(".", 1)
        file_part = f"{module_part.replace('.', '/')}.py"
        if file_part in repo_files and symbol_part in file_symbols.get(file_part, set()):
            return True, {file_part} if file_part in spec_set else set()

    return False, set()

def _raise_if_dependency_graph_has_cycle(graph: Dict[str, Set[str]]) -> None:
    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def visit(path: str) -> None:
        if path in visiting:
            start = stack.index(path)
            cycle = stack[start:] + [path]
            raise ValueError(f"file dependency cycle detected: {' -> '.join(cycle)}")
        if path in visited:
            return
        visiting.add(path)
        stack.append(path)
        for dep in graph.get(path, set()):
            if dep in graph:
                visit(dep)
        stack.pop()
        visiting.remove(path)
        visited.add(path)

    for path in graph:
        visit(path)

def validate_sds_semantics(sds_json: Dict[str, Any]) -> None:
    sds_json = normalize_sds_candidate(sds_json)
    repo_file_list = _flatten_repo_file_list(sds_json["repo_structure"])
    if len(repo_file_list) != len(set(repo_file_list)):
        seen = set()
        duplicates = []
        for path in repo_file_list:
            if path in seen and path not in duplicates:
                duplicates.append(path)
            seen.add(path)
        raise ValueError(f"duplicate files in repo_structure: {duplicates}")
    repo_files = set(repo_file_list)

    # file_specs 覆盖的文件必须存在于 repo_structure
    spec_paths = [fs["path"] for fs in sds_json["file_specs"]]
    if len(spec_paths) != len(set(spec_paths)):
        raise ValueError("duplicate file_specs.path entries are not allowed")
    missing = [p for p in spec_paths if p not in repo_files]
    if missing:
        raise ValueError(f"file_specs.path not in repo_structure: {missing}")
    # dev_plan 必须唯一覆盖 file_specs 中的每个文件且不多不少
    assigned = {}
    for a in sds_json["dev_plan"]:
        for fp in a["file_paths"]:
            if fp in assigned:
                raise ValueError(f"file assigned to multiple developers: {fp} -> {assigned[fp]} & {a['developer_id']}")
            assigned[fp] = a["developer_id"]
    spec_set = set(spec_paths)
    assigned_set = set(assigned.keys())
    if spec_set != assigned_set:
        raise ValueError(f"dev_plan must cover exactly file_specs. missing={list(spec_set-assigned_set)}, extra={list(assigned_set-spec_set)}")

    dev_ids = {a["developer_id"] for a in sds_json["dev_plan"]}
    for fs in sds_json["file_specs"]:
        owner = fs.get("owner")
        if not owner:
            raise ValueError(f"missing owner for file_spec: {fs['path']}")
        if owner not in dev_ids:
            raise ValueError(f"file_spec owner not in dev_plan: {fs['path']} -> {owner}")
        assigned_owner = assigned.get(fs["path"])
        if assigned_owner != owner:
            raise ValueError(f"file_spec owner does not match dev_plan: {fs['path']} -> {owner} != {assigned_owner}")

    symbol_to_files, file_symbols = _collect_declared_symbols(sds_json["file_specs"])
    graph = {path: set() for path in spec_set}
    for fs in sds_json["file_specs"]:
        path = fs["path"]
        for dependency in fs.get("dependencies", []):
            ok, targets = _resolve_dependency_targets(
                dependency,
                repo_files=repo_files,
                spec_set=spec_set,
                symbol_to_files=symbol_to_files,
                file_symbols=file_symbols,
            )
            if not ok:
                raise ValueError(f"dependency does not point to a declared file or symbol: {path} -> {dependency}")
            graph[path].update(target for target in targets if target in spec_set)
    _raise_if_dependency_graph_has_cycle(graph)

    # tech_stack 语言受支持（示例：仅 python）
    if sds_json["tech_stack"]["language"].lower() not in {"python"}:
        raise ValueError("unsupported language in this PoC; only python is supported")

def validate_sds(sds_json: Dict[str, Any]) -> None:
    normalized = normalize_sds_candidate(sds_json)
    validate_sds_structure(normalized)
    validate_sds_semantics(normalized)

def validate_update_reason(ur_json: Dict[str, Any]) -> None:
    _jsonschema_validate(ur_json, UPDATE_REASON_SCHEMA)
    _require(isinstance(ur_json, dict), "update reason must be an object")
    for key in (
        "target_file",
        "file_path",
        "change_type",
        "rationale",
        "related_files_brief_used",
        "modified_exported_symbols",
        "compatibility_note",
        "affected_dependent_files",
    ):
        _require(key in ur_json, f"missing update reason field: {key}")

def validate_qa_test_bundle(bundle_json: Dict[str, Any]) -> None:
    _jsonschema_validate(bundle_json, QA_TEST_BUNDLE_SCHEMA)
    _require(isinstance(bundle_json, dict), "QA bundle must be an object")
    tests = bundle_json.get("tests")
    _require(isinstance(tests, dict) and tests, "QA bundle tests must be a non-empty object")
    for path, content in tests.items():
        _require(isinstance(path, str) and path.startswith("tests/"), f"invalid test path: {path!r}")
        _require(isinstance(content, str), f"test content must be a string: {path!r}")
    run_command = bundle_json.get("run_command")
    _require(isinstance(run_command, str) and run_command.strip(), "run_command must be a non-empty string")
