"""Validation of generated QA artifacts without consulting hidden tests."""
import ast
from pathlib import PurePosixPath
from core.contracts import repository_path


def validate_test_sources(bundle, sds):
    from core.schemas import _collect_declared_symbols, _module_name
    _, declared = _collect_declared_symbols(sds["file_specs"])
    modules = {_module_name(path): path for path in declared}
    modules.update({m[4:]: p for m, p in list(modules.items()) if m.startswith("src.")})
    for path, code in bundle["tests"].items():
        repository_path(path)
        tree = ast.parse(code, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in modules:
                target = modules[node.module]
                for alias in node.names:
                    if alias.name != "*" and alias.name not in declared[target]:
                        raise ValueError(f"QA imports undeclared interface: {node.module}.{alias.name}")
    for path, deps in bundle.get("test_dependencies", {}).items():
        if path not in bundle["tests"] or not set(deps).issubset(declared):
            raise ValueError(f"Invalid declared QA dependencies: {path}")
    for path, fixtures in bundle.get("fixture_dependencies", {}).items():
        if path not in bundle["tests"] or not set(fixtures).issubset(bundle["tests"]):
            raise ValueError(f"Invalid QA fixture dependencies: {path}")


def assertion_inventory(tests):
    result = {}
    for path, code in tests.items():
        try:
            tree = ast.parse(code)
            result[path] = [ast.dump(n.test) for n in ast.walk(tree) if isinstance(n, ast.Assert)]
        except SyntaxError:
            result[path] = None
    return result


def assert_preserves_tests(before, after):
    """A test-source repair may fix imports/syntax, never silently weaken assertions."""
    from collections import Counter
    for path, old in before.items():
        if path not in after: raise ValueError(f"QA repair removed test file: {path}")
        new = after[path]
        for marker in ("pytest.skip", "pytest.xfail", "@pytest.mark.skip", "@pytest.mark.xfail"):
            if new.count(marker) > old.count(marker): raise ValueError("QA repair added a skip/xfail")
        try:
            old_tree, new_tree = ast.parse(old), ast.parse(new)
        except SyntaxError:
            if new.count("assert ") < old.count("assert "): raise ValueError("QA repair removed assertions")
            continue
        old_asserts = Counter(ast.dump(n.test) for n in ast.walk(old_tree) if isinstance(n, ast.Assert))
        new_asserts = Counter(ast.dump(n.test) for n in ast.walk(new_tree) if isinstance(n, ast.Assert))
        if old_asserts - new_asserts: raise ValueError("QA repair changed or removed existing assertions")
        old_names = {n.name for n in ast.walk(old_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}
        new_names = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}
        if not old_names.issubset(new_names): raise ValueError("QA repair removed test functions")
