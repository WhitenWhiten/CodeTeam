from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set


DEFAULT_ARCHITECT_PREFERENCES: tuple[str, ...] = (
    "minimal functional architecture with the smallest coherent module set",
    "layered architecture with explicit domain, service, and adapter boundaries",
    "class-oriented architecture with stable public types and methods",
    "testability-first architecture with narrow pure functions and simple fixtures",
    "package-oriented architecture that isolates CLI/API entrypoints from core logic",
    "configuration-aware architecture with explicit shared settings and dependency boundaries",
)


@dataclass(frozen=True)
class ArchitectProfile:
    name: str
    preference: str
    claimed_summary: str


def build_architect_profiles(count: int, seed: int | None = None) -> List[ArchitectProfile]:
    rng = random.Random(seed)
    indexes = list(range(max(1, count)))
    rng.shuffle(indexes)

    profiles: List[ArchitectProfile] = []
    for order, idx in enumerate(indexes):
        preference = DEFAULT_ARCHITECT_PREFERENCES[idx % len(DEFAULT_ARCHITECT_PREFERENCES)]
        profiles.append(
            ArchitectProfile(
                name=f"Architect-{idx + 1}",
                preference=preference,
                claimed_summary="No prior module claims.",
            )
        )
    return profiles


def update_claimed_summary(prior_sds_candidates: Sequence[Dict[str, Any]], limit: int = 12) -> str:
    modules: Set[str] = set()
    intents: List[str] = []

    for candidate in prior_sds_candidates:
        modules.update(_top_level_modules(candidate.get("repo_structure", [])))
        problem = str(candidate.get("problem") or "").strip()
        notes = str(candidate.get("notes") or "").strip()
        intent = problem or notes
        if intent and intent not in intents:
            intents.append(intent[:180])

    if not modules and not intents:
        return "No prior module claims."

    module_text = ", ".join(sorted(modules)[:limit]) or "none"
    intent_text = " | ".join(intents[:3]) or "none"
    return f"Previously claimed top-level modules: {module_text}. Prior design intents: {intent_text}."


def _top_level_modules(repo_structure: Iterable[Any]) -> Set[str]:
    modules: Set[str] = set()
    for node in repo_structure or []:
        path = ""
        if isinstance(node, str):
            path = node
        elif isinstance(node, dict):
            path = str(node.get("path") or "")
        else:
            path = str(getattr(node, "path", "") or "")
        path = path.replace("\\", "/").strip("/")
        if not path:
            continue
        first = path.split("/", 1)[0]
        if first not in {"src", "tests", "test", "lib", "app", "docs"}:
            modules.add(first)
        if isinstance(node, dict) and node.get("children"):
            modules.update(_top_level_modules(node["children"]))
    return modules


GENERIC_MODULES = {"src", "tests", "test", "lib", "app", "docs"}


def design_descriptor(candidate):
    import hashlib, json
    from core.dependencies import resolve_file_dependencies
    specs = candidate["file_specs"]
    graph = resolve_file_dependencies(specs, strict=False)
    apis = {p["path"] + ":" + str(x.get("signature", x.get("name", ""))) for p in specs
            for k in ("functions", "classes") for x in p["interfaces"].get(k, [])}
    modules=set()
    for spec in specs:
        parts=spec["path"].split("/")[:-1]
        modules.update(p for p in parts if p not in GENERIC_MODULES)
    # Name-independent structural fingerprint; not a proof of non-isomorphism.
    colors={s["path"]:str((len(s["interfaces"].get("functions", [])),len(s["interfaces"].get("classes", [])),len(graph[s["path"]]))) for s in specs}
    for _ in range(len(specs)):
        colors={p:hashlib.sha256(json.dumps([colors[p], sorted(colors[d] for d in graph[p])]).encode()).hexdigest() for p in graph}
    canonical=sorted([{k:v for k,v in s.items() if k not in {"owner", "responsibilities"}} for s in specs],key=lambda s:s["path"])
    return {"files":sorted(graph),"apis":sorted(apis),"modules":sorted(modules),
            "topology_fingerprint":hashlib.sha256(json.dumps(sorted(colors.values())).encode()).hexdigest(),
            "exact_fingerprint":hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()}


def compare_designs(candidate, previous, threshold=0.98):
    current=design_descriptor(candidate)
    comparisons=[]
    for index, prior in enumerate(previous):
        other=design_descriptor(prior)
        row={"candidate_index":index}
        for key in ("files","apis","modules"):
            a,b=set(current[key]),set(other[key])
            row[key+"_jaccard"]=len(a&b)/len(a|b) if a|b else 1.0
        row["same_topology"]=current["topology_fingerprint"]==other["topology_fingerprint"]
        row["exact_duplicate"]=current["exact_fingerprint"]==other["exact_fingerprint"]
        row["near_duplicate"]=row["same_topology"] and all(row[k+"_jaccard"]>=threshold for k in ("files","apis","modules"))
        comparisons.append(row)
    return {"descriptor":current,"comparisons":comparisons,"duplicate":any(r["exact_duplicate"] or r["near_duplicate"] for r in comparisons),
            "structural_limit":"Rename-invariant graph summary may collide; metrics do not establish semantic diversity."}
