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
        modules.add(path.split("/", 1)[0])
    return modules
