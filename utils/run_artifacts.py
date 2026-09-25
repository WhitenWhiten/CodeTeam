from __future__ import annotations

import json
import os
import tempfile
import time
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
from core.contracts import to_jsonable


class RunArtifacts:
    def __init__(self, base_dir: str | None, enabled: bool = True):
        self.enabled = enabled and bool(base_dir)
        self.root = Path(base_dir).resolve() if self.enabled else None
        self._lease = None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create_for_workspace(cls, workspace, run_id=None, enabled=True):
        name = run_id or time.strftime('run-%Y%m%d-%H%M%S-') + uuid4().hex[:8]
        return cls(str(Path(workspace) / 'run_artifacts' / name), enabled)

    def acquire(self):
        if not self.root:
            return
        self._lease = open(self.root / '.run.lock', 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self._lease.seek(0, 2)
                if self._lease.tell() == 0:
                    self._lease.write(b'0')
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            self._lease = None
            raise RuntimeError('Another process owns this run directory') from exc

    def release(self):
        if self._lease:
            self._lease.close()
            self._lease = None

    def _path(self, relative_path):
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Artifact path escapes run directory')
        return path

    def _atomic_bytes(self, relative_path, data):
        if not self.root:
            return
        path = self._path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write_json(self, relative_path, payload):
        self.write_text(relative_path, json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2))

    def write_text(self, relative_path, text):
        self._atomic_bytes(relative_path, (text or '').encode('utf-8'))

    def read_json(self, relative_path):
        if not self.root:
            raise RuntimeError('Run artifacts are disabled')
        return json.loads(self._path(relative_path).read_text(encoding='utf-8'))

    def copy_file(self, source, relative_path):
        source = Path(source)
        if self.root and source.is_file():
            self._atomic_bytes(relative_path, source.read_bytes())

    def event(self, kind, **payload):
        if not self.root:
            return
        entry = {'time': datetime.now(timezone.utc).isoformat(), 'kind': kind, **payload}
        with open(self.root / 'events.jsonl', 'a', encoding='utf-8') as out:
            out.write(json.dumps(to_jsonable(entry), ensure_ascii=False) + '\n')
            out.flush()
            os.fsync(out.fileno())
