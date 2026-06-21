# actions/run_tests.py
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Dict, Mapping
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

class RunTestsAction(Action):
    def __init__(self):
        try:
            super().__init__()  # Compatible with metagpt.Action
        except TypeError:
        # Compatible with the local placeholder Action(name: str="")
            super().__init__(name="RunTestsAction")

    def _safe_test_path(self, path: str) -> Path:
        normalized = (path or "").replace("\\", "/").strip()
        if not normalized.startswith("tests/") or ".." in normalized.split("/"):
            raise ValueError(f"invalid QA test path: {path!r}")
        return Path(".codeteam_qa") / normalized

    def _write_temp_tests(self, repo_root: Path, tests: Mapping[str, str]) -> Path:
        qa_root = repo_root / ".codeteam_qa"
        if qa_root.exists():
            shutil.rmtree(qa_root)
        for path, content in tests.items():
            target = repo_root / self._safe_test_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return qa_root / "tests"

    def _point_pytest_at_temp_tests(self, run_command: str, temp_tests_dir: Path) -> str:
        temp_rel = temp_tests_dir.as_posix()
        if "pytest" not in (run_command or ""):
            return run_command

        parts = run_command.split()
        if not parts:
            return f"pytest -q {temp_rel}"

        next_parts = []
        changed_target = False
        has_temp_target = False
        for part in parts:
            quote_prefix = part[:1] if part[:1] in {"'", '"'} else ""
            quote_suffix = part[-1:] if part[-1:] in {"'", '"'} else ""
            bare = part.strip("'\"")
            normalized = bare.replace("\\", "/")

            replacement = None
            if normalized.startswith(".codeteam_qa/"):
                has_temp_target = True
            elif normalized in {"tests", "tests/", "./tests", "./tests/"}:
                replacement = temp_rel
            elif normalized.startswith("tests/"):
                replacement = f".codeteam_qa/{normalized}"
            elif normalized.startswith("./tests/"):
                replacement = f".codeteam_qa/{normalized[2:]}"
            elif normalized == ".":
                replacement = temp_rel

            if replacement is not None:
                changed_target = True
                next_parts.append(f"{quote_prefix}{replacement}{quote_suffix}")
            else:
                next_parts.append(part)

        if not changed_target and not has_temp_target:
            next_parts.append(temp_rel)
        return " ".join(next_parts)

    def _record_setup_commands(self, setup_commands: list[str] | None) -> list[Dict[str, str]]:
        records = []
        for command in setup_commands or []:
            records.append(
                {
                    "command": command,
                    "status": "skipped",
                    "reason": "setup_commands are recorded but not executed by this minimal QA runtime",
                }
            )
        return records

    async def run(
        self,
        repo_root,
        run_command,
        runtime_adapter,
        tests: Mapping[str, str] | None = None,
        setup_commands: list[str] | None = None,
    ):
        root = Path(repo_root)
        qa_root = root / ".codeteam_qa"
        setup_records = self._record_setup_commands(setup_commands)
        original_command = run_command or "pytest -q"
        effective_command = original_command

        try:
            if tests:
                temp_tests_dir = self._write_temp_tests(root, tests)
                effective_command = self._point_pytest_at_temp_tests(original_command, temp_tests_dir.relative_to(root))

            result = runtime_adapter.run_tests(str(root), effective_command)
            if hasattr(result, "__await__"):
                result = await result

            result.setdefault("setup_commands", setup_records)
            result["qa_run_command"] = {
                "original": run_command,
                "effective": effective_command,
            }
            if setup_records:
                result["output"] = (
                    (result.get("output") or "")
                    + "\n"
                    + "\n".join(
                        f"SETUP {record['status']}: {record['command']} ({record['reason']})"
                        for record in setup_records
                    )
                ).strip()
            return result
        finally:
            if tests and qa_root.exists():
                shutil.rmtree(qa_root)
