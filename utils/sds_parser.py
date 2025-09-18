# utils/sds_parser.py
from __future__ import annotations
from core.models import SDS, RepoNode, FileSpec, DevAssignment, FuncBrief, ClassBrief
from typing import Dict, Any, List

def _node(d: Dict[str, Any]) -> RepoNode:
    return RepoNode(path=d["path"], type=d["type"], children=[_node(c) for c in d.get("children", [])])

def _func(d): return FuncBrief(name=d["name"], signature=d["signature"], doc=d.get("doc",""))
def _cls(d): return ClassBrief(name=d["name"], init_signature=d.get("init_signature",""),
                               methods=[_func(m) for m in d.get("methods",[])], doc=d.get("doc",""))

def parse_sds(sds_json: Dict[str, Any]) -> SDS:
    repo_nodes = [_node(n) for n in sds_json["repo_structure"]]
    file_specs = []
    for fs in sds_json["file_specs"]:
        interfaces = {
            "functions": [ _func(f) for f in fs["interfaces"]["functions"]],
            "classes": [ _cls(c) for c in fs["interfaces"]["classes"]],
        }
        file_specs.append(FileSpec(path=fs["path"],
                                   responsibilities=fs["responsibilities"],
                                   interfaces=interfaces,
                                   dependencies=fs.get("dependencies", [])))
    dev_plan = [DevAssignment(developer_id=a["developer_id"], file_paths=a["file_paths"]) for a in sds_json["dev_plan"]]
    return SDS(id=sds_json["id"], problem=sds_json["problem"], tech_stack=sds_json["tech_stack"],
               repo_structure=repo_nodes, file_specs=file_specs, dev_plan=dev_plan,
               constraints=sds_json.get("constraints", {}), notes=sds_json.get("notes",""))