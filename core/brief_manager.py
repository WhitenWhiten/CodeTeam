from copy import deepcopy
from typing import Any, Dict, Optional
from threading import RLock

class BriefManager:
    def __init__(self, artifacts=None):
        self._briefs: Dict[str, dict] = {}
        self._lock = RLock()
        self.artifacts = artifacts
        self.events = []
        if artifacts and artifacts.root and (artifacts.root / "interfaces/journal.json").exists():
            self.events = artifacts.read_json("interfaces/journal.json")
            self.replay()

    def replay(self):
        with self._lock:
            self._briefs = {}
            for event in self.events:
                if event["kind"] == "publish":
                    self._briefs[event["file_path"]] = deepcopy(event["brief"])

    def record(self, kind, **payload):
        with self._lock:
            event = {"sequence": len(self.events) + 1, "kind": kind, **deepcopy(payload)}
            updated = self.events + [event]
            if self.artifacts:
                self.artifacts.write_json("interfaces/journal.json", updated)
            self.events = updated
            return event["sequence"]

    def versions(self, paths):
        with self._lock:
            return {p: {k: self._briefs.get(p, {}).get(k) for k in ("source_hash", "interface_version", "commit_sha")} for p in paths}

    def consume(self, consumer, paths):
        versions = self.versions(paths)
        self.record("consume", consumer=consumer, dependencies=versions)
        return versions

    def assert_current(self, versions):
        if self.versions(versions) != versions:
            raise StaleBriefContext("Dependency versions changed during generation")

    def _public_summary(self, entry: Optional[dict]) -> dict | None:
        if entry is None:
            return None
        allowed = {
            "origin", "constants", "attributes", "reexports", "imports", "interface_version",
            "parent_interface_version", "source_hash", "commit_sha", "publication_id", "invariant_sources",
            "functions",
            "classes",
            "error",
            "latest_update_reason",
            "compatibility_note",
            "invariants",
            "typed_signatures",
        }
        summary = {k: deepcopy(v) for k, v in entry.items() if k in allowed}
        return summary

    def update_brief(
        self,
        file_path: str,
        brief: dict,
        update_reason: Optional[Dict[str, Any]] = None,
        compatibility_note: Optional[str] = None,
        invariants: Optional[list[str]] = None,
        typed_signatures: Optional[Dict[str, str] | list[str]] = None,
    ):
        with self._lock:
            entry = deepcopy(brief or {})
            embedded_reason = entry.pop("latest_update_reason", None) or entry.pop("update_reason", None)
            latest_update_reason = update_reason or embedded_reason
            if latest_update_reason is not None:
                entry["latest_update_reason"] = deepcopy(latest_update_reason)

            note = compatibility_note
            if note is None and latest_update_reason:
                note = latest_update_reason.get("compatibility_note")
            if note is None:
                note = entry.get("compatibility_note")
            if note is not None:
                entry["compatibility_note"] = note

            if invariants is not None:
                entry["invariants"] = deepcopy(invariants)
            elif "invariants" not in entry:
                entry["invariants"] = []

            if typed_signatures is not None:
                entry["typed_signatures"] = deepcopy(typed_signatures)
            elif "typed_signatures" not in entry:
                entry["typed_signatures"] = []

            accepted = self._public_summary(entry) or {}
            if accepted == self._briefs.get(file_path):
                return
            accepted["publication_id"] = len(self.events) + 1
            self.record("publish", file_path=file_path, brief=accepted)
            self._briefs[file_path] = accepted

    def get_brief(self, file_path: str) -> dict | None:
        with self._lock:
            return self._public_summary(self._briefs.get(file_path))

    def list_available(self):
        with self._lock:
            return list(self._briefs.keys())


class StaleBriefContext(RuntimeError):
    pass
