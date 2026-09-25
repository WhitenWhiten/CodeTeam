from __future__ import annotations
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from utils.run_artifacts import RunArtifacts

IGNORED = {'.git', '__pycache__', '.pytest_cache', '.codeteam_qa', '.venv'}

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, value):
    path = Path(path)
    RunArtifacts(str(path.parent)).write_json(path.name, value)

def files_digest(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f'Missing artifact directory: {root}')
    files = {}
    for path in sorted(root.rglob('*')):
        if any(part in IGNORED for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Artifact contains a link: {path}')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files

def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    hashes = files_digest(source)
    if destination.exists():
        if files_digest(destination) != hashes:
            raise ValueError('Published artifact already exists with different contents')
    else:
        destination.mkdir(parents=True)
        for relative in hashes:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
    return {'path': str(destination), 'files': hashes, 'sha256': digest(hashes)}

def verify_artifact(artifact):
    if files_digest(artifact['path']) != artifact['files'] or digest(artifact['files']) != artifact['sha256']:
        raise ValueError('Published artifact was changed after generation')
