from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class RepoNode:
    path: str
    type: str  # "file" | "dir"
    children: List["RepoNode"] = field(default_factory=list)

@dataclass
class FuncBrief:
    name: str
    signature: str
    doc: str = ""

@dataclass
class ClassBrief:
    name: str
    init_signature: str = ""
    methods: List[FuncBrief] = field(default_factory=list)
    doc: str = ""

@dataclass
class FileSpec:
    path: str
    responsibilities: str
    interfaces: Dict[str, List]  # {"functions":[FuncBrief], "classes":[ClassBrief]}
    dependencies: List[str] = field(default_factory=list)

@dataclass
class DevAssignment:
    developer_id: str
    file_paths: List[str]

@dataclass
class SDS:
    id: str
    problem: str
    tech_stack: Dict
    repo_structure: List[RepoNode]
    file_specs: List[FileSpec]
    dev_plan: List[DevAssignment]
    constraints: Dict = field(default_factory=dict)
    notes: str = ""

@dataclass
class UpdateReason:
    file_path: str
    change_type: str
    functions_added: List[FuncBrief] = field(default_factory=list)
    functions_modified: List[FuncBrief] = field(default_factory=list)
    functions_removed: List[FuncBrief] = field(default_factory=list)
    classes_added: List[ClassBrief] = field(default_factory=list)
    classes_modified: List[ClassBrief] = field(default_factory=list)
    classes_removed: List[ClassBrief] = field(default_factory=list)
    rationale: str = ""
    related_files_brief_used: List[str] = field(default_factory=list)