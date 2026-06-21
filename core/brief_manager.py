from copy import deepcopy
from typing import Any, Dict, Optional
from threading import RLock

class BriefManager:
    def __init__(self):
        self._briefs: Dict[str, dict] = {}
        self._lock = RLock()

    def _public_summary(self, entry: Optional[dict]) -> dict | None:
        if entry is None:
            return None
        allowed = {
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

            self._briefs[file_path] = self._public_summary(entry) or {}

    def get_brief(self, file_path: str) -> dict | None:
        with self._lock:
            return self._public_summary(self._briefs.get(file_path))

    def list_available(self):
        with self._lock:
            return list(self._briefs.keys())
