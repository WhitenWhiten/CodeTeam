# core/ast_utils.py
from __future__ import annotations
import ast
from typing import Dict, List

def _format_args(args: ast.arguments) -> str:
    return ast.unparse(args)


def _signature(node):
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({_format_args(node.args)}){returns}:"

def to_brief(code: str) -> Dict:
    tree = ast.parse(code)
    functions = []
    classes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _signature(node)
            doc = ast.get_docstring(node) or ""
            functions.append({"name": node.name, "signature": sig, "doc": doc})
        elif isinstance(node, ast.ClassDef):
            init_sig = ""
            methods = []
            for b in node.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _signature(b)
                    doc = ast.get_docstring(b) or ""
                    methods.append({"name": b.name, "signature": sig, "doc": doc})
                    if b.name == "__init__":
                        init_sig = sig
            doc = ast.get_docstring(node) or ""
            classes.append({"name": node.name, "init_signature": init_sig, "methods": methods, "doc": doc})
    return {"functions": functions, "classes": classes}
