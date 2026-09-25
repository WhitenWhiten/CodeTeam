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
