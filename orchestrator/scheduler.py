from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple


class SchedulerError(RuntimeError):
    """Raised when SDS file scheduling cannot proceed."""


@dataclass(frozen=True)
class ScheduledFile:
    owner: str
    file_path: str
    priority: Tuple[int, int, int]


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip()


class DependencyScheduler:
    """Dependency-aware file scheduler for SDS file_specs.

    Dependencies are limited to files declared in the same SDS. Any dependency
    that does not match a declared file_spec path is treated as an external
    package or undeclared resource and is ignored for scheduling.
    """

    def __init__(self, sds_or_file_specs: Any, dev_plan: Sequence[Any] | None = None):
        if dev_plan is None and hasattr(sds_or_file_specs, "file_specs"):
            file_specs = list(sds_or_file_specs.file_specs)
            dev_plan = list(getattr(sds_or_file_specs, "dev_plan", []))
        else:
            file_specs = list(sds_or_file_specs)
            dev_plan = list(dev_plan or [])

        if not file_specs:
            raise SchedulerError("SDS has no file_specs to schedule")

        self.files: List[str] = []
        self.order: Dict[str, int] = {}
        for idx, fs in enumerate(file_specs):
            path = _normalize_path(_get_value(fs, "path", ""))
            if not path:
                raise SchedulerError(f"file_specs[{idx}] is missing path")
            if path in self.order:
                raise SchedulerError(f"duplicate file_spec path: {path}")
            self.order[path] = idx
            self.files.append(path)

        self.file_set: Set[str] = set(self.files)
        self.dependencies: Dict[str, Set[str]] = {}
        self.ignored_dependencies: Dict[str, Set[str]] = {}
        for fs in file_specs:
            path = _normalize_path(_get_value(fs, "path", ""))
            deps = {_normalize_path(dep) for dep in _get_value(fs, "dependencies", []) or []}
            internal = {dep for dep in deps if dep in self.file_set}
            self.dependencies[path] = internal
            self.ignored_dependencies[path] = deps - internal

        self.dependents: Dict[str, Set[str]] = {path: set() for path in self.files}
        for path, deps in self.dependencies.items():
            for dep in deps:
                self.dependents[dep].add(path)

        self.owner_order: List[str] = []
        self.owner_by_file: Dict[str, str] = {}
        for assignment in dev_plan:
            owner = str(_get_value(assignment, "developer_id", "")).strip()
            if not owner:
                raise SchedulerError("dev_plan contains an assignment without developer_id")
            if owner not in self.owner_order:
                self.owner_order.append(owner)
            for file_path in _get_value(assignment, "file_paths", []) or []:
                normalized = _normalize_path(file_path)
                if normalized not in self.file_set:
                    continue
                if normalized in self.owner_by_file:
                    raise SchedulerError(
                        f"file assigned to multiple developers: {normalized}"
                    )
                self.owner_by_file[normalized] = owner

        missing_owner = [path for path in self.files if path not in self.owner_by_file]
        if missing_owner:
            raise SchedulerError(f"file_specs missing developer owner: {missing_owner}")

        self.topological_order = self._validate_acyclic()
        self.depth: Dict[str, int] = self._compute_depths()
        self.fanout: Dict[str, int] = {
            path: len(self.dependents[path]) for path in self.files
        }
        self.priorities: Dict[str, Tuple[int, int, int]] = {
            path: (self.depth[path], self.fanout[path], -self.order[path])
            for path in self.files
        }

        self.pending: Set[str] = set(self.files)
        self.running: Dict[str, str] = {}
        self.completed: Set[str] = set()

    def owner_for(self, file_path: str) -> str:
        path = _normalize_path(file_path)
        try:
            return self.owner_by_file[path]
        except KeyError as exc:
            raise SchedulerError(f"unknown scheduled file: {file_path}") from exc

    def priority_for(self, file_path: str) -> Tuple[int, int, int]:
        path = _normalize_path(file_path)
        try:
            return self.priorities[path]
        except KeyError as exc:
            raise SchedulerError(f"unknown scheduled file: {file_path}") from exc

    def direct_dependents(self, file_path: str) -> List[str]:
        path = _normalize_path(file_path)
        if path not in self.file_set:
            raise SchedulerError(f"unknown scheduled file: {file_path}")
        return sorted(self.dependents[path], key=lambda item: self.order[item])

    def ready_files(self, owner: str | None = None) -> List[str]:
        owner_filter = str(owner).strip() if owner is not None else None
        ready = [
            path
            for path in self.pending
            if (owner_filter is None or self.owner_by_file[path] == owner_filter)
            and self.dependencies[path].issubset(self.completed)
        ]
        return sorted(ready, key=lambda path: self.priorities[path], reverse=True)

    def dispatch_ready(self) -> List[ScheduledFile]:
        dispatched: List[ScheduledFile] = []
        busy_owners = set(self.running.values())
        for owner in self.owner_order:
            if owner in busy_owners:
                continue
            candidates = self.ready_files(owner)
            if not candidates:
                continue
            path = candidates[0]
            self.pending.remove(path)
            self.running[path] = owner
            busy_owners.add(owner)
            dispatched.append(
                ScheduledFile(owner=owner, file_path=path, priority=self.priorities[path])
            )
        return dispatched

    def complete(self, file_path: str) -> None:
        path = _normalize_path(file_path)
        if path in self.completed:
            return
        if path not in self.running:
            if path in self.pending:
                raise SchedulerError(f"cannot complete pending file: {path}")
            raise SchedulerError(f"cannot complete unknown or non-running file: {path}")
        del self.running[path]
        self.completed.add(path)

    def requeue_files(self, file_paths: Iterable[str]) -> List[str]:
        requeued: List[str] = []
        seen: Set[str] = set()
        for file_path in file_paths:
            path = _normalize_path(file_path)
            if not path or path in seen:
                continue
            seen.add(path)
            if path not in self.file_set:
                raise SchedulerError(f"cannot requeue unknown file: {file_path}")
            if path in self.running:
                raise SchedulerError(f"cannot requeue running file: {path}")
            if path not in self.pending:
                self.completed.discard(path)
                self.pending.add(path)
            requeued.append(path)
        return requeued

    def requeue_from_fixes(
        self, fixes: Sequence[Mapping[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        payloads: Dict[str, Dict[str, Any]] = {}
        to_requeue: List[str] = []

        for fix in fixes:
            file_path = _normalize_path(str(fix.get("file_path", "")))
            if not file_path:
                continue
            if file_path not in self.file_set:
                raise SchedulerError(f"fix references unknown file: {file_path}")

            issues = fix.get("issues", {}) or {}
            payloads[file_path] = {
                "type": "fix",
                "file_path": file_path,
                "issues": issues,
            }
            to_requeue.append(file_path)

            public_api_changed = bool(
                fix.get("public_api_changed", issues.get("public_api_changed", False))
            )
            affected_dependents = self._affected_dependents(fix, issues)
            if public_api_changed:
                affected_dependents.extend(self.direct_dependents(file_path))

            for dependent in affected_dependents:
                dependent_path = _normalize_path(dependent)
                if (
                    not dependent_path
                    or dependent_path == file_path
                    or dependent_path not in self.file_set
                ):
                    continue
                payloads.setdefault(
                    dependent_path,
                    {
                        "type": "fix",
                        "file_path": dependent_path,
                        "issues": {
                            "upstream_file": file_path,
                            "reason": "dependent requeued after upstream API change",
                        },
                    },
                )
                to_requeue.append(dependent_path)

        self.requeue_files(to_requeue)
        return payloads

    def has_work(self) -> bool:
        return bool(self.pending or self.running)

    def is_running(self, file_path: str) -> bool:
        return _normalize_path(file_path) in self.running

    def running_files(self) -> List[str]:
        return sorted(self.running, key=lambda path: self.order[path])

    def assert_can_progress(self) -> None:
        if self.pending and not self.running and not self.ready_files():
            raise SchedulerError(self._blocked_message())

    def _validate_acyclic(self) -> List[str]:
        indegree = {path: len(self.dependencies[path]) for path in self.files}
        ready = [path for path in self.files if indegree[path] == 0]
        processed: List[str] = []

        while ready:
            ready.sort(key=lambda path: self.order[path])
            path = ready.pop(0)
            processed.append(path)
            for downstream in sorted(self.dependents[path], key=lambda item: self.order[item]):
                indegree[downstream] -= 1
                if indegree[downstream] == 0:
                    ready.append(downstream)

        if len(processed) != len(self.files):
            cycle_nodes = [path for path in self.files if indegree[path] > 0]
            raise SchedulerError(
                "cycle detected in SDS file dependencies: "
                + " -> ".join(cycle_nodes)
            )
        return processed

    def _compute_depths(self) -> Dict[str, int]:
        depth = {path: 0 for path in self.files}
        for path in reversed(self.topological_order):
            downstream = self.dependents[path]
            if downstream:
                depth[path] = 1 + max(depth[item] for item in downstream)
        return depth

    def _blocked_message(self) -> str:
        parts = []
        for path in sorted(self.pending, key=lambda item: self.order[item]):
            missing = sorted(
                self.dependencies[path] - self.completed,
                key=lambda item: self.order[item],
            )
            parts.append(f"{path} waiting for {missing}")
        return "unable to schedule pending files; unresolved dependencies: " + "; ".join(parts)

    def _affected_dependents(
        self, fix: Mapping[str, Any], issues: Mapping[str, Any]
    ) -> List[str]:
        raw = fix.get("affected_dependents", issues.get("affected_dependents", []))
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, Sequence):
            return [str(item) for item in raw]
        return []
