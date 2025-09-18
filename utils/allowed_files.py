# utils/allowed_files.py
from typing import List, Set

def flatten_repo_structure(repo_nodes: List[dict]) -> List[str]:
    paths = []
    def walk(n, base=""):
        p = f"{base}/{n['path']}".lstrip("/")
        if n["type"] == "file":
            paths.append(p)
        else:
            for c in n.get("children", []):
                walk(c, p)
    for node in repo_nodes:
        walk(node, "")
    return paths