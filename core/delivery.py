"""Explicit producers and final delivery checks for every planned file."""
from pathlib import Path
import ast
import re


def delivery_rules(sds, repo_files):
    specs = {f["path"] for f in sds["file_specs"]}
    declared = sds.get("file_rules", [])
    rules = {r["path"]: dict(r) for r in declared}
    if len(rules) != len(declared): raise ValueError("Duplicate file production rules")
    if set(rules) - set(repo_files): raise ValueError("File rule outside repository tree")
    if set(rules) & specs: raise ValueError("A file cannot have both a Developer and a static/QA producer")
    for path in set(repo_files) - specs:
        if path in rules: continue
        if path.startswith("tests/"):
            rules[path] = {"path": path, "kind": "qa_temporary", "producer": "qa", "allow_empty": True}
        elif path.endswith("/__init__.py") or path == "__init__.py":
            rules[path] = {"path": path, "kind": "package_marker", "producer": "static", "content": "", "allow_empty": True}
        else:
            raise ValueError(f"Missing file producer/owner: {path}")
    for path, rule in rules.items():
        if rule["producer"] == "static":
            if "content" not in rule: raise ValueError(f"Static file has no content rule: {path}")
            if not rule.get("allow_empty", False) and not rule["content"].strip():
                raise ValueError(f"Empty required static file: {path}")
        elif rule["producer"] != "qa" or rule["kind"] != "qa_temporary" or not path.startswith("tests/"):
            raise ValueError(f"Unsupported file producer: {path}")
    dependencies = sds.get("dependencies", []) + sds["tech_stack"].get("dependencies", [])
    if dependencies and not ({"requirements.txt", "pyproject.toml"} & (specs | set(rules))):
        raise ValueError("Declared dependencies require a planned requirements.txt or pyproject.toml producer")
    return rules


def initialize_static_files(repo, sds):
    rules = delivery_rules(sds, repo.allowed_files_all)
    for path, rule in rules.items():
        if rule["producer"] == "static": repo.write_file(path, rule.get("content", ""))
    return rules


def check_delivery(repo, sds):
    rules = delivery_rules(sds, repo.allowed_files_all)
    temporary = {p for p, r in rules.items() if r["kind"] == "qa_temporary"}
    empty_ok = {p for p, r in rules.items() if r.get("allow_empty")}
    required = set(repo.allowed_files_all) - temporary
    failures = []
    for path in sorted(required):
        if not repo.is_file(path): failures.append({"path": path, "reason": "missing"}); continue
        content = repo.read_file(path)
        if not content.strip() and path not in empty_ok: failures.append({"path": path, "reason": "empty_required_file"})
        if path.endswith(".py"):
            try: ast.parse(content)
            except SyntaxError as exc: failures.append({"path": path, "reason": str(exc)})
    dependencies = sds.get("dependencies", []) + sds["tech_stack"].get("dependencies", [])
    manifests = "\n".join(repo.read_file(p) for p in ("requirements.txt", "pyproject.toml") if repo.is_file(p))
    normalized = re.sub(r"[-_.]+", "-", manifests.lower())
    for requirement in dependencies:
        name = re.split(r"[\[<>=!~ ;@]", requirement, 1)[0]
        if re.sub(r"[-_.]+", "-", name.lower()) not in normalized:
            failures.append({"path": "dependency_manifest", "reason": f"Missing declared dependency: {requirement}"})
    return {"success": not failures, "required_files": sorted(required), "temporary_files": sorted(temporary), "failures": failures}


def remove_temporary_placeholders(repo, report):
    for path in report["temporary_files"]:
        target = Path(repo.root) / path
        # QA writes elsewhere. A nonempty file here signals an unaccounted mutation.
        if target.exists():
            if target.read_bytes().strip(): raise ValueError(f"Unexpected contents in temporary QA placeholder: {path}")
            target.unlink()
