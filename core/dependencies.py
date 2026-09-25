"""Resolve SDS dependency aliases identically in scheduling and context."""
from core.contracts import to_jsonable
from core.schemas import _collect_declared_symbols, _resolve_dependency_targets


def resolve_file_dependencies(file_specs, repo_files=None):
    specs = [to_jsonable(spec) for spec in file_specs]
    paths = {spec["path"] for spec in specs}
    symbols, file_symbols = _collect_declared_symbols(specs)
    result = {}
    for spec in specs:
        targets = set()
        for ref in spec.get("dependencies", []):
            ok, resolved = _resolve_dependency_targets(ref, set(repo_files or paths), paths, symbols, file_symbols)
            if not ok:
                raise ValueError(f"Unresolved dependency: {spec['path']} -> {ref}")
            targets.update(resolved)
        result[spec["path"]] = targets - {spec["path"]}
    return result
