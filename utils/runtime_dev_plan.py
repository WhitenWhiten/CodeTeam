from __future__ import annotations

from copy import deepcopy
import random
from typing import Any, Dict, Iterable, List, Optional

from core.models import DevAssignment


def build_fixed_random_dev_plan(
    file_paths: Iterable[str],
    fixed_agent_count: int = 4,
    assignment_seed: Optional[int] = None,
) -> List[DevAssignment]:
    paths = list(dict.fromkeys(file_paths))
    agent_count = max(1, int(fixed_agent_count or 4))
    rng = random.Random(assignment_seed)
    rng.shuffle(paths)

    buckets: List[List[str]] = [[] for _ in range(agent_count)]
    for index, path in enumerate(paths):
        buckets[index % agent_count].append(path)

    return [
        DevAssignment(developer_id=f"Dev-{index + 1}", file_paths=buckets[index])
        for index in range(agent_count)
    ]


def build_runtime_sds_json(
    sds_json: Dict[str, Any],
    dynamic_enabled: bool,
    fixed_agent_count: int = 4,
    assignment_seed: Optional[int] = None,
    ownership: Optional[str] = None,
) -> Dict[str, Any]:
    runtime_sds = deepcopy(sds_json)
    if ownership is not None:
        original=runtime_sds["dev_plan"]
        paths=[fs["path"] for fs in runtime_sds["file_specs"]]
        count=len(original) if dynamic_enabled else min(fixed_agent_count,len(paths))
        groups=[list(a["file_paths"]) for a in original]
        if ownership == "sds":
            while len(groups)>count:
                groups[-2].extend(groups.pop())
            while len(groups)<count:
                largest=max(range(len(groups)),key=lambda i:len(groups[i]))
                groups.append([groups[largest].pop()])
        else:
            if ownership == "random": random.Random(assignment_seed).shuffle(paths)
            groups=[paths[i::count] for i in range(count)]
        runtime_sds["dev_plan"]=[{"developer_id":original[i]["developer_id"] if dynamic_enabled else f"Dev-{i+1}","file_paths":group} for i,group in enumerate(groups) if group]
        owners={p:a["developer_id"] for a in runtime_sds["dev_plan"] for p in a["file_paths"]}
        for spec in runtime_sds["file_specs"]: spec["owner"]=owners[spec["path"]]
        return runtime_sds
    if dynamic_enabled:
        return runtime_sds

    file_paths = [fs["path"] for fs in runtime_sds.get("file_specs", [])]
    runtime_dev_plan = build_fixed_random_dev_plan(
        file_paths=file_paths,
        fixed_agent_count=fixed_agent_count,
        assignment_seed=assignment_seed,
    )
    runtime_sds["dev_plan"] = [
        {"developer_id": item.developer_id, "file_paths": list(item.file_paths)}
        for item in runtime_dev_plan if item.file_paths
    ]
    owners = {p: a["developer_id"] for a in runtime_sds["dev_plan"] for p in a["file_paths"]}
    for spec in runtime_sds.get("file_specs", []):
        spec["owner"] = owners[spec["path"]]

    notes = runtime_sds.get("notes", "").strip()
    override_note = (
        f"runtime override: developer allocation fixed to {fixed_agent_count} agents;"
        " architect-provided developer ownership ignored"
    )
    runtime_sds["notes"] = f"{notes}\n{override_note}".strip()
    return runtime_sds
