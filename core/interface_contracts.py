"""Syntactic interface contracts; never executes model-provided declarations."""
from __future__ import annotations
import ast
import re


def parse_signature(signature: str):
    text = signature.strip()
    if not text.startswith(("def ", "async def ")):
        text = "def " + text
    text = text.rstrip(":").strip() + ":\n    pass"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(f"Invalid function signature: {signature}") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError(f"Expected one function signature: {signature}")
    node = tree.body[0]
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
        raise ValueError("Signature must not contain a function body")
    return node


def validate_interfaces(interfaces):
    names = set()
    for fn in interfaces.get("functions", []):
        node = parse_signature(fn["signature"])
        if node.name != fn["name"]:
            raise ValueError(f"Interface name/signature mismatch: {fn['name']} != {node.name}")
        if fn["name"] in names:
            raise ValueError(f"Duplicate interface symbol: {fn['name']}")
        names.add(fn["name"])
    for cls in interfaces.get("classes", []):
        name = cls["name"]
        if not name.isidentifier() or name in names:
            raise ValueError(f"Invalid or duplicate class symbol: {name}")
        names.add(name)
        validate_interfaces({"functions": cls.get("methods", [])})
        if cls.get("init_signature"):
            init = parse_signature(cls["init_signature"])
            if init.name != "__init__":
                raise ValueError("init_signature must declare __init__")
            declared = next((m for m in cls.get("methods", []) if m["name"] == "__init__"), None)
            if declared and ast.dump(parse_signature(declared["signature"])) != ast.dump(init):
                raise ValueError("Conflicting constructor signatures")


def validate_runtime(stack):
    if stack["language"].lower() != "python" or stack["test_framework"].lower() != "pytest":
        raise ValueError("Supported execution stack is Python + pytest")
    runtime = str(stack.get("runtime", "")).lower().strip()
    if not re.fullmatch(r"(?:cpython|python)?\s*3(?:\.\d+){0,2}\+?", runtime):
        raise ValueError(f"Unsupported Python runtime declaration: {runtime}")


def _annotation_expr(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try: return ast.dump(ast.parse(node.value, mode="eval").body)
        except SyntaxError: pass
    return ast.dump(node) if node is not None else None


def _expr(node):
    return ast.dump(node) if node is not None else None


def compare_signature(expected, actual):
    """Exact calling convention/defaults; annotations are required only when declared."""
    if type(expected) is not type(actual):
        raise ValueError(f"sync/async mismatch: {expected.name}")
    left, right = expected.args, actual.args
    for field in ("posonlyargs", "args", "kwonlyargs"):
        a, b = getattr(left, field), getattr(right, field)
        if [x.arg for x in a] != [x.arg for x in b]:
            raise ValueError(f"Parameter contract mismatch: {expected.name}.{field}")
        for x, y in zip(a, b):
            if x.annotation is not None and _annotation_expr(x.annotation) != _annotation_expr(y.annotation):
                raise ValueError(f"Annotation contract mismatch: {expected.name}.{x.arg}")
    for field in ("vararg", "kwarg"):
        a, b = getattr(left, field), getattr(right, field)
        if (a.arg if a else None) != (b.arg if b else None):
            raise ValueError(f"Variadic contract mismatch: {expected.name}")
        if a and a.annotation is not None and _annotation_expr(a.annotation) != _annotation_expr(b.annotation):
            raise ValueError(f"Variadic annotation mismatch: {expected.name}")
    for field in ("defaults", "kw_defaults"):
        if [_expr(x) for x in getattr(left, field)] != [_expr(x) for x in getattr(right, field)]:
            raise ValueError(f"Default contract mismatch: {expected.name}")
    if expected.returns is not None and _annotation_expr(expected.returns) != _annotation_expr(actual.returns):
        raise ValueError(f"Return annotation mismatch: {expected.name}")


def validate_implementation(code, interfaces):
    tree = ast.parse(code)
    actual = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for fn in interfaces.get("functions", []):
        if fn["name"] not in actual: raise ValueError(f"Missing declared function: {fn['name']}")
        compare_signature(parse_signature(fn["signature"]), actual[fn["name"]])
    for cls in interfaces.get("classes", []):
        node = actual.get(cls["name"])
        if not isinstance(node, ast.ClassDef): raise ValueError(f"Missing declared class: {cls['name']}")
        methods = {n.name: n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        declarations = list(cls.get("methods", []))
        if cls.get("init_signature"):
            declarations.append({"name": "__init__", "signature": cls["init_signature"]})
        for method in declarations:
            if method["name"] not in methods: raise ValueError(f"Missing declared method: {method['name']}")
            compare_signature(parse_signature(method["signature"]), methods[method["name"]])
    return tree


def local_imports(tree, path, repo_files):
    """Resolve static repository imports; external and dynamic references stay explicit."""
    modules = {}
    for file in repo_files:
        if not file.endswith(".py"): continue
        module = file[:-3].replace("/", ".")
        if module.endswith(".__init__"): module = module[:-9]
        modules[module] = file
        if module.startswith("src."): modules[module[4:]] = file
    own = path[:-3].replace("/", ".")
    package = own[:-9] if own.endswith(".__init__") else own.rpartition(".")[0]
    local, external, dynamic = set(), set(), []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import): names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                if node.level > len(parts): raise ValueError(f"Relative import escapes package: {path}")
                base = ".".join(parts[:len(parts)-node.level+1] + ([base] if base else []))
            names = [base] + [base + "." + a.name for a in node.names if a.name != "*"]
        elif isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == "__import__") or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")):
            dynamic.append(ast.unparse(node))
        for name in names:
            if name in modules: local.add(modules[name])
            elif name: external.add(name)
    return {"local": sorted(local - {path}), "external_or_unresolved": sorted(external), "dynamic_unknown": dynamic}


def validate_import_contract(tree, path, repo_files, dependencies):
    report = local_imports(tree, path, repo_files)
    # Package initializers are implicit import infrastructure, not business task edges.
    undeclared = set(report["local"]) - set(dependencies)
    undeclared = {f for f in undeclared if not f.endswith("/__init__.py")}
    if undeclared: raise ValueError(f"Undeclared repository imports in {path}: {sorted(undeclared)}")
    return report
