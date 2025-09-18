from typing import Dict
from threading import RLock

class BriefManager:
    def __init__(self):
        self._briefs: Dict[str, dict] = {}
        self._lock = RLock()

    def update_brief(self, file_path: str, brief: dict):
        with self._lock:
            self._briefs[file_path] = brief

    def get_brief(self, file_path: str) -> dict | None:
        with self._lock:
            return self._briefs.get(file_path)

    def list_available(self):
        with self._lock:
            return list(self._briefs.keys())