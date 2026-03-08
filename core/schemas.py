# core/schemas.py
from __future__ import annotations
from typing import Dict, Any, Set
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
  "required": ["file_path", "change_type", "rationale", "related_files_brief_used"],
  "properties": {
    "file_path": {"type": "string"},
    "change_type": {"type": "string", "enum": ["create", "modify"]},
    "functions_added": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "functions_modified": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "functions_removed": {"type": "array", "items": {"$ref": "#/$defs/FuncBrief"}, "default": []},
    "classes_added": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
    "classes_modified": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
    "classes_removed": {"type": "array", "items": {"$ref": "#/$defs/ClassBrief"}, "default": []},
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
    _jsonschema_validate(sds_json, SDS_SCHEMA)
    _require(isinstance(sds_json, dict), "SDS must be an object")
    for key in ("id", "problem", "tech_stack", "repo_structure", "file_specs", "dev_plan"):
        _require(key in sds_json, f"missing SDS field: {key}")
    _require(isinstance(sds_json["repo_structure"], list) and sds_json["repo_structure"], "repo_structure must be a non-empty list")
    _require(isinstance(sds_json["file_specs"], list) and sds_json["file_specs"], "file_specs must be a non-empty list")
    _require(isinstance(sds_json["dev_plan"], list) and sds_json["dev_plan"], "dev_plan must be a non-empty list")

def _flatten_repo_files(nodes) -> Set[str]:
    files = set()
    def walk(n, base=""):
        p = f"{base}/{n['path']}".lstrip("/")
        if n["type"] == "file":
            files.add(p)
        else:
            for c in n.get("children", []):
                walk(c, p)
    for node in nodes:
        walk(node, "")
    return files

def validate_sds_semantics(sds_json: Dict[str, Any]) -> None:
    repo_files = _flatten_repo_files(sds_json["repo_structure"])
    # file_specs 覆盖的文件必须存在于 repo_structure
    spec_paths = [fs["path"] for fs in sds_json["file_specs"]]
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
    # tech_stack 语言受支持（示例：仅 python）
    if sds_json["tech_stack"]["language"].lower() not in {"python"}:
        raise ValueError("unsupported language in this PoC; only python is supported")

def validate_sds(sds_json: Dict[str, Any]) -> None:
    validate_sds_structure(sds_json)
    validate_sds_semantics(sds_json)

def validate_update_reason(ur_json: Dict[str, Any]) -> None:
    _jsonschema_validate(ur_json, UPDATE_REASON_SCHEMA)
    _require(isinstance(ur_json, dict), "update reason must be an object")
    for key in ("file_path", "change_type", "rationale", "related_files_brief_used"):
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
