# actions/run_tests.py
from __future__ import annotations
import shutil
import subprocess
import asyncio
import inspect
import shlex
import os
from pathlib import Path
from typing import Dict, Mapping
from runtime_adapters.runner import python_module_args, command_args
from core.contracts import repository_path
from runtime_adapters.process import run_process
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
        normalized = repository_path(path or "")
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

        parts = command_args(run_command)
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
        return subprocess.list2cmdline(next_parts) if os.name == "nt" else shlex.join(next_parts)

    def _is_allowed_setup_command(self, command: str) -> bool:
        normalized = " ".join((command or "").strip().split()).lower()
        allowed_prefixes = (
            "pip --version",
            "pip install ",
            "python -m pip --version",
            "python -m pip install ",
            "python3 -m pip install ",
            "pytest ",
            "python -m pytest ",
        )
        return any(normalized.startswith(prefix) for prefix in allowed_prefixes)

    async def _run_setup_commands(self, repo_root: Path, setup_commands: list[str] | None, adapter) -> list[Dict[str, str]]:
        records = []
        for command in setup_commands or []:
            try:
                argv = python_module_args(command, adapter.python_executable, setup=True)
            except ValueError:
                records.append(
                    {
                        "command": command,
                        "status": "blocked",
                        "returncode": None,
                        "output": "",
                        "reason": "setup command is outside the allowed install/test command set",
                    }
                )
                continue
            try:
                proc = await run_process(argv, repo_root, adapter.timeout)
                records.append(
                    {
                        "command": command,
                        "status": "success" if proc["returncode"] == 0 and not proc["timed_out"] else "failed",
                        "returncode": proc["returncode"],
                        "output": proc["output"],
                        "reason": "setup timed out" if proc["timed_out"] else "",
                    }
                )
            except OSError as exc:
                records.append(
                    {
                        "command": command,
                        "status": "failed",
                        "returncode": None,
                        "output": str(exc),
                        "reason": "setup executable could not be started",
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
        setup_records = await self._run_setup_commands(root, setup_commands, runtime_adapter)
        original_command = run_command or "pytest -q"
        effective_command = original_command

        try:
            blocking_setup = [record for record in setup_records if record["status"] in {"failed", "blocked"}]
            if blocking_setup:
                output = "\n".join(
                    f"SETUP {record['status']}: {record['command']} {record.get('reason', '')}\n{record.get('output', '')}".strip()
                    for record in blocking_setup
                )
                return {
                    "success": False,
                    "status": "setup_error",
                    "output": output,
                    "failures": [
                        {
                            "file_path": "",
                            "message": "setup command failed",
                            "category": "setup_error",
                            "stack": output,
                        }
                    ],
                    "setup_commands": setup_records,
                    "qa_run_command": {
                        "original": run_command,
                        "effective": effective_command,
                    },
                }

            if tests:
                temp_tests_dir = self._write_temp_tests(root, tests)
                effective_command = self._point_pytest_at_temp_tests(original_command, temp_tests_dir.relative_to(root))

            method = getattr(runtime_adapter, "run_tests_async", runtime_adapter.run_tests)
            if inspect.iscoroutinefunction(method):
                result = await method(str(root), effective_command)
            else:
                result = await asyncio.to_thread(method, str(root), effective_command)

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
                        f"SETUP {record['status']}: {record['command']}"
                        for record in setup_records
                    )
                ).strip()
            return result
        finally:
            if tests and qa_root.exists():
                shutil.rmtree(qa_root)
