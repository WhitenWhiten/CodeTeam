# core/ast_utils.py
from __future__ import annotations
import ast
from typing import Dict, List

def _format_args(args: ast.arguments) -> str:
    parts = []
    def fmt(arg):
        if isinstance(arg.annotation, ast.AST):
            ann = ast.unparse(arg.annotation)
            return f"{arg.arg}: {ann}"
        return arg.arg
    pos = [fmt(a) for a in args.posonlyargs] + [fmt(a) for a in args.args]
    if args.vararg:
        pos.append("*" + args.vararg.arg)
    kw = [fmt(a) for a in args.kwonlyargs]
    if args.kwarg:
        kw.append("**" + args.kwarg.arg)
    defaults = []  # 简化：不展开默认值
    args_sig = ", ".join(pos + kw)
    return args_sig

def to_brief(code: str) -> Dict:
    tree = ast.parse(code)
    functions = []
    classes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            sig = f"def {node.name}({_format_args(node.args)}) -> Any:"
            doc = ast.get_docstring(node) or ""
            functions.append({"name": node.name, "signature": sig, "doc": doc})
        elif isinstance(node, ast.ClassDef):
            init_sig = ""
            methods = []
            for b in node.body:
                if isinstance(b, ast.FunctionDef):
                    sig = f"def {b.name}({_format_args(b.args)}) -> Any:"
                    doc = ast.get_docstring(b) or ""
                    methods.append({"name": b.name, "signature": sig, "doc": doc})
                    if b.name == "__init__":
                        init_sig = sig
            doc = ast.get_docstring(node) or ""
            classes.append({"name": node.name, "init_signature": init_sig, "methods": methods, "doc": doc})
    return {"functions": functions, "classes": classes}