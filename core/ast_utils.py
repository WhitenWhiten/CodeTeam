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
    return {"functions": functions, "classes": classes, **_extra_surface(tree)}


def _extra_surface(tree):
    constants, exports, imports, attributes = [], [], [], []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and (not target.id.startswith("_") or target.id == "__all__"):
                    constants.append({"name": target.id, "value": ast.unparse(node.value) if node.value else None,
                                      "annotation": ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) else None})
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.unparse(node))
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if not name.startswith("_"):
                    exports.append({"name": name, "source": ast.unparse(node)})
        if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef)) and node.decorator_list:
            attributes.append({"name":node.name+".<decorators>","value":[ast.unparse(d) for d in node.decorator_list]})
        if isinstance(node, ast.ClassDef):
            attributes.append({"name":node.name+".<class-contract>","value":{
                "bases":[ast.unparse(b) for b in node.bases],"keywords":[ast.unparse(k) for k in node.keywords],
                "decorators":[ast.unparse(d) for d in node.decorator_list]}})
            for method in node.body:
                if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and not method.name.startswith("_"):
                    attributes.append({"name":node.name+"."+method.name+".<decorators>","value":[ast.unparse(d) for d in method.decorator_list]})
            for child in ast.walk(node):
                if isinstance(child, (ast.Assign, ast.AnnAssign)):
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    for target in targets:
                        name = target.id if isinstance(target, ast.Name) and child in node.body else (target.attr if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in {"self", "cls"} else "")
                        if name and not name.startswith("_"):
                            attributes.append({"name": node.name + "." + name, "value": ast.unparse(child.value) if child.value else None})
    return {"constants": constants, "reexports": exports, "imports": sorted(imports), "attributes": attributes}


def public_surface(brief):
    """Conservative syntax surface: docs/bodies/private helpers are excluded.

    Public bindings, imports and attribute expressions count as potential impacts,
    not proof of a breaking change. Dynamic behavior still requires retesting.
    """
    result = {}
    exported=set()
    for entry in brief.get("constants",[]):
        if entry["name"]=="__all__":
            try: exported.update(ast.literal_eval(entry["value"]))
            except (ValueError,TypeError,SyntaxError): pass
    for kind in ("functions", "classes", "constants", "reexports", "attributes"):
        result[kind] = []
        for row in brief.get(kind, []):
            if row["name"].startswith("_") and row["name"] not in exported and row["name"]!="__all__":
                continue
            item = {k: v for k, v in row.items() if k not in {"doc", "methods"}}
            if "methods" in row:
                item["methods"] = [{k: v for k, v in m.items() if k != "doc"} for m in row["methods"]
                                   if not m["name"].startswith("_") or m["name"].startswith("__")]
            result[kind].append(item)
        result[kind].sort(key=lambda x: x["name"])
    result["imports"] = sorted(brief.get("imports", []))
    return result


def interface_version(brief):
    import hashlib, json
    return hashlib.sha256(json.dumps(public_surface(brief), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
