# actions/generate_code.py
from __future__ import annotations
from pathlib import Path
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

from core.ast_utils import to_brief
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

    def _build_prompt(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], issues: Optional[Dict[str, Any]] = None) -> str:
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
        briefs_pretty = "\n".join(brief_lines) if brief_lines else "(none)"

        issues_excerpt = ""
        if issues:
            stack = issues.get("stack", "")
            issues_excerpt = stack[:2000]  # Keep the prompt compact.

        tpl = self._load_prompt_template()
        return tpl.format(
            file_path=file_spec["path"],
            responsibilities=file_spec.get("responsibilities", ""),
            interfaces_pretty=interfaces_pretty,
            briefs_pretty=briefs_pretty,
            issues_excerpt=issues_excerpt or "(none)"
        )

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
        prompt = self._build_prompt(file_spec, briefs, issues)
        raw_code = await llm.text(prompt)

        # Strip Markdown/HTML code fences so writes and AST parsing receive clean source.
        code = strip_code_fences(raw_code)

        lock_factory = getattr(repo_manager, "collaboration_lock", None)
        if lock_factory is None:
            from contextlib import nullcontext
            lock_factory = nullcontext

        with lock_factory():
            checkout = getattr(repo_manager, "checkout_agent_branch", None)
            if checkout:
                checkout(agent_id)

            # Use modify for existing files and create for new files.
            change_type = "modify" if repo_manager.exists(file_spec["path"]) else "create"

            # Write code subject to agent permissions.
            repo_manager.write_file(file_spec["path"], code, agent_id=agent_id)

            # Build a brief and tolerate syntax errors from malformed generated code.
            try:
                brief = to_brief(code)
            except SyntaxError:
                brief = {"functions": [], "classes": [], "error": "syntax error in generated code"}

            modified_exported_symbols = self._exported_symbols(brief)
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

            # Delegate commit details to RepoManager.commit_file.
            repo_manager.commit_file(file_spec["path"], ur, agent_id)
            brief["latest_update_reason"] = ur
            brief["compatibility_note"] = compatibility_note
            brief["typed_signatures"] = self._typed_signatures(brief)
            brief.setdefault("invariants", [])
            return brief
