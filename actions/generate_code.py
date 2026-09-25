# actions/generate_code.py
from __future__ import annotations
from pathlib import Path
import json
import hashlib
from typing import Dict, Any, Optional

try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

from core.ast_utils import to_brief, public_surface, interface_version
from core.interface_contracts import validate_implementation, validate_import_contract
from core.dependencies import resolve_file_dependencies
from core.text_utils import strip_code_fences

DEV_PROMPT_FALLBACK = """# FILE_PATH: {file_path}
You are a senior software engineer. Your task is to implement or fix one source file and ensure the result can be written directly to the target repository.

Output contract:
- Output only the complete source code for the target file.
- Do not output Markdown, code fences, explanations, introductory comments, or any extra text.
- Do not create, modify, or propose changes to files other than the target file.

Implementation constraints:
- The target file path is fixed as `{file_path}`.
- You must implement the functions, classes, and methods declared in `interfaces`; you may add necessary internal helpers, but do not expand the public interface without reason.
- Depend only on the provided file briefs; do not assume access to the full source code of other files.
- The code must be compatible with the current PoC's Python + pytest execution environment.
- Prefer clear type annotations, stable public interfaces, and useful docstrings.

Target file responsibilities:
{responsibilities}

Interface definitions:
{interfaces_pretty}

Other file briefs (read-only):
{briefs_pretty}

Fix context (ignore if empty):
{issues_excerpt}
"""

class GenerateCodeAction(Action):
    def __init__(self, llm=None):
        try:
            # Compatible with metagpt.Action's no-argument constructor.
            super().__init__()
        except TypeError:
            # Compatible with the local placeholder Action(name: str="").
            super().__init__(name="GenerateCodeAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path(__file__).resolve().parents[1] / "prompts" / "developer_prompt.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return DEV_PROMPT_FALLBACK

    def _build_prompt(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], issues: Optional[Dict[str, Any]] = None, current_source: str = "") -> str:
        functions = file_spec["interfaces"].get("functions", [])
        classes = file_spec["interfaces"].get("classes", [])
        iface_lines = []
        for f in functions:
            iface_lines.append(f"- function: {f['signature']}  # {f.get('doc','')}")
        for c in classes:
            iface_lines.append(f"- class: {c['name']}")
            if c.get("init_signature"):
                iface_lines.append(f"  init: {c['init_signature']}")
            for m in c.get("methods", []):
                iface_lines.append(f"  method: {m['signature']}  # {m.get('doc','')}")
        interfaces_pretty = "\n".join(iface_lines) if iface_lines else "(none)"

        brief_lines = []
        for path, b in briefs.items():
            brief_lines.append(f"* {path}")
            for f in b.get("functions", []):
                brief_lines.append(f"  - {f['signature']}")
            for c in b.get("classes", []):
                brief_lines.append(f"  - class {c['name']}")
                for m in c.get("methods", []):
                    brief_lines.append(f"    - {m['signature']}")
        briefs_pretty = json.dumps(briefs, ensure_ascii=False, indent=2) if briefs else "(none)"

        issues_excerpt = ""
        if issues:
            issues_excerpt = json.dumps(issues, ensure_ascii=False, indent=2)

        tpl = self._load_prompt_template()
        prompt = tpl.format(
            file_path=file_spec["path"],
            responsibilities=file_spec.get("responsibilities", ""),
            interfaces_pretty=interfaces_pretty,
            briefs_pretty=briefs_pretty,
            issues_excerpt=issues_excerpt or "(none)"
        )
        return prompt + ("\n\nCurrent target file (complete):\n" + (current_source or "(new file)")
                         + "\n\nReturn the complete replacement file. Preserve unrelated behavior, helpers and public interfaces.")

    def _validate_candidate(self, code, file_spec):
        if not code.strip():
            raise ValueError("Generated file is empty")
        if not file_spec["path"].endswith(".py"):
            return {"functions": [], "classes": []}
        tree = validate_implementation(code, file_spec["interfaces"])
        brief = to_brief(code)
        if getattr(self, "repo_specs", None):
            deps = resolve_file_dependencies(self.repo_specs, getattr(self, "repo_files", None))
            brief["import_check"] = validate_import_contract(tree, file_spec["path"], self.repo_files, deps[file_spec["path"]])
        for kind in ("functions", "classes"):
            actual = {item["name"]: item for item in brief[kind]}
            for expected in file_spec["interfaces"].get(kind, []):
                if expected["name"] not in actual:
                    raise ValueError(f"Missing declared {kind}: {expected['name']}")
                if kind == "classes":
                    methods = {m["name"] for m in actual[expected["name"]]["methods"]}
                    required = {m["name"] for m in expected.get("methods", [])}
                    if expected.get("init_signature"):
                        required.add("__init__")
                    if not required.issubset(methods):
                        raise ValueError(f"Missing declared methods: {sorted(required - methods)}")
        return brief

    def _interface_delta(self, before, after):
        before, after = public_surface(before), public_surface(after)
        delta = {"previous_interface_version": interface_version(before), "interface_version": interface_version(after)}
        changed = []
        if before["imports"] != after["imports"]:
            changed.append("<imports>")
            delta["imports_changed"] = {"before": before["imports"], "after": after["imports"]}
        for kind in ("functions", "classes", "constants", "reexports", "attributes"):
            old = {x["name"]: x for x in before.get(kind, [])}
            new = {x["name"]: x for x in after.get(kind, [])}
            delta[kind + "_added"] = [new[n] for n in sorted(new.keys() - old.keys())]
            delta[kind + "_removed"] = [old[n] for n in sorted(old.keys() - new.keys())]
            delta[kind + "_modified"] = [new[n] for n in sorted(old.keys() & new.keys()) if old[n] != new[n]]
            for suffix in ("_added", "_removed", "_modified"):
                changed.extend(x["name"] for x in delta[kind + suffix])
        return delta, sorted(set(changed))

    def _exported_symbols(self, brief: Dict[str, Any]) -> list[str]:
        symbols: list[str] = []
        for func in brief.get("functions", []) or []:
            name = func.get("name")
            if name:
                symbols.append(name)
        for cls in brief.get("classes", []) or []:
            name = cls.get("name")
            if name:
                symbols.append(name)
        return symbols

    def _typed_signatures(self, brief: Dict[str, Any]) -> list[str]:
        signatures: list[str] = []
        for func in brief.get("functions", []) or []:
            sig = func.get("signature")
            if sig:
                signatures.append(sig)
        for cls in brief.get("classes", []) or []:
            if cls.get("init_signature"):
                signatures.append(cls["init_signature"])
            for method in cls.get("methods", []) or []:
                sig = method.get("signature")
                if sig:
                    signatures.append(sig)
        return signatures

    def _affected_dependent_files(self, file_spec: Dict[str, Any], issues: Optional[Dict[str, Any]]) -> list[str]:
        if not issues:
            return []
        raw = (
            issues.get("affected_dependent_files")
            or issues.get("affected_dependents")
            or issues.get("dependent_files")
            or []
        )
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        target = file_spec.get("path")
        result = []
        for item in raw:
            if isinstance(item, str) and item and item != target and item not in result:
                result.append(item)
        return result

    def _compatibility_note(
        self,
        change_type: str,
        modified_exported_symbols: list[str],
        affected_dependent_files: list[str],
        issues: Optional[Dict[str, Any]],
    ) -> str:
        if issues and issues.get("public_api_changed"):
            return "Public API may have changed; dependent files should be rechecked."
        if affected_dependent_files:
            return "Potential downstream impact inferred from QA issues."
        if change_type == "create":
            return "New file; no existing callers should be broken."
        if modified_exported_symbols:
            return "Exported symbols preserved or updated in place; no known compatibility break."
        return "No exported symbol changes detected."

    async def run(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], llm, repo_manager, agent_id: str, issues: Optional[Dict[str, Any]] = None):
        path = file_spec["path"]
        manager = getattr(self, "brief_manager", None)
        consumed = manager.consume(path, briefs) if manager else {}
        current = repo_manager.read_file(path) if repo_manager.exists(path) else ""
        try:
            previous = to_brief(current) if path.endswith(".py") else {"functions": [], "classes": []}
        except SyntaxError:
            previous = {"functions": [], "classes": []}
        feedback = dict(issues or {})
        for attempt in range(3):
            prompt = self._build_prompt(file_spec, briefs, feedback, current)
            code = strip_code_fences(await llm.text(prompt))
            try:
                brief = self._validate_candidate(code, file_spec)
                break
            except (SyntaxError, ValueError) as exc:
                if attempt == 2:
                    raise ValueError(f"Invalid generation for {path}: {exc}") from exc
                feedback["generation_validation_error"] = str(exc)
                feedback["rejected_candidate"] = code

        lock_factory = getattr(repo_manager, "collaboration_lock", None)
        if lock_factory is None:
            from contextlib import nullcontext
            lock_factory = nullcontext

        with lock_factory():
            if manager:
                manager.assert_current(consumed)
            checkout = getattr(repo_manager, "checkout_agent_branch", None)
            if checkout:
                checkout(agent_id)
            latest = repo_manager.read_file(path) if repo_manager.exists(path) else ""
            if latest != current:
                raise RuntimeError(f"Target file changed while generating {path}; refusing stale overwrite")

            # Use modify for existing files and create for new files.
            change_type = "modify" if repo_manager.exists(file_spec["path"]) else "create"

            # Write code subject to agent permissions.
            repo_manager.write_file(file_spec["path"], code, agent_id=agent_id)

            delta, modified_exported_symbols = self._interface_delta(previous, brief)
            affected_dependent_files = self._affected_dependent_files(file_spec, issues)
            compatibility_note = self._compatibility_note(
                change_type,
                modified_exported_symbols,
                affected_dependent_files,
                issues,
            )

            ur = {
                "target_file": file_spec["path"],
                "file_path": file_spec["path"],
                "change_type": change_type,
                "functions_added": [] if change_type == "modify" else brief.get("functions", []),
                "functions_modified": brief.get("functions", []) if change_type == "modify" else [],
                "functions_removed": [],
                "classes_added": [] if change_type == "modify" else brief.get("classes", []),
                "classes_modified": brief.get("classes", []) if change_type == "modify" else [],
                "classes_removed": [],
                "modified_exported_symbols": modified_exported_symbols,
                "compatibility_note": compatibility_note,
                "affected_dependent_files": affected_dependent_files,
                "rationale": "fix implementation per QA feedback" if issues else "initial implementation based on file_spec",
                "related_files_brief_used": list(briefs.keys())
            }
            ur.update(delta)
            ur["public_api_changed"] = bool(current.strip() and modified_exported_symbols)
            if ur["public_api_changed"]:
                ur["compatibility_note"] = "Exported interface changed; revalidate dependents."

            # Delegate commit details to RepoManager.commit_file.
            ur["dependency_versions"] = consumed
            ur["source_hash"] = hashlib.sha256(repo_manager.read_bytes(path)).hexdigest()
            commit_sha = repo_manager.commit_file(file_spec["path"], ur, agent_id)
            if getattr(repo_manager, "git_enabled", False) and commit_sha is None:
                commit_sha = repo_manager._git("rev-parse", "HEAD").stdout.strip()
            brief["commit_sha"] = commit_sha
            brief["source_hash"] = ur["source_hash"]
            brief["interface_version"] = ur["interface_version"]
            brief["parent_interface_version"] = ur["previous_interface_version"]
            brief["latest_update_reason"] = ur
            brief["compatibility_note"] = ur["compatibility_note"]
            brief["typed_signatures"] = self._typed_signatures(brief)
            brief.setdefault("invariants", [])
            return brief
