"""Explicit producers and final delivery checks for every planned file."""
from pathlib import Path
import ast
import re
import posixpath
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


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


def _manifest_dependency_names(repo):
    """Read install declarations; comments, metadata and constraints are not dependencies."""
    names = set()
    visited = set()
    active = set()

    def read_requirements(path):
        if path in active: raise ValueError(f"Circular requirements include: {path}")
        if path in visited: return
        if path not in repo.allowed_files_all or not repo.is_file(path):
            raise ValueError(f"Requirements include is not a delivered planned file: {path}")
        active.add(path)
        for raw in repo.read_file(path).replace("\\\n", "").splitlines():
            line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
            if not line or line.startswith("#"): continue
            include = re.match(r"^(?:-r\s*|--requirement(?:=|\s+))(.+)$", line)
            if include:
                target = include.group(1).strip().strip(chr(34) + chr(39))
                read_requirements(posixpath.normpath(posixpath.join(posixpath.dirname(path), target)))
            elif not line.startswith("-"):
                line = re.split(r"\s+--hash(?:=|\s+)", line, maxsplit=1)[0]
                names.add(canonicalize_name(Requirement(line).name))
        active.remove(path)
        visited.add(path)

    if repo.is_file("requirements.txt"): read_requirements("requirements.txt")
    if repo.is_file("pyproject.toml"):
        document = tomllib.loads(repo.read_file("pyproject.toml"))
        declared = document.get("project", {}).get("dependencies", [])
        if not isinstance(declared, list) or any(not isinstance(r, str) for r in declared):
            raise ValueError("project.dependencies must be a list of requirement strings")
        names.update(canonicalize_name(Requirement(r).name) for r in declared)
        poetry = document.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if not isinstance(poetry, dict): raise ValueError("tool.poetry.dependencies must be a table")
        names.update(canonicalize_name(name) for name in poetry if name != "python")
    return names


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
    try:
        manifest_names = _manifest_dependency_names(repo)
        for requirement in dependencies:
            if canonicalize_name(Requirement(requirement).name) not in manifest_names:
                failures.append({"path": "dependency_manifest", "reason": f"Missing declared dependency: {requirement}"})
    except (ValueError, TypeError, AttributeError) as exc:
        failures.append({"path": "dependency_manifest", "reason": f"Invalid dependency declaration: {exc}"})
    return {"success": not failures, "required_files": sorted(required), "temporary_files": sorted(temporary), "failures": failures}


def remove_temporary_placeholders(repo, report):
    for path in report["temporary_files"]:
        target = Path(repo.root) / path
        # QA writes elsewhere. A nonempty file here signals an unaccounted mutation.
        if target.exists():
            if target.read_bytes().strip(): raise ValueError(f"Unexpected contents in temporary QA placeholder: {path}")
            target.unlink()
