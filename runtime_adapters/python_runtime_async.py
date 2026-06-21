# runtime_adapters/python_runtime_async.py
from __future__ import annotations
import asyncio
import importlib.util
import re
import shlex
import shutil
from typing import Dict, Any, List
from pathlib import Path

from runtime_adapters.pytest_fallback import run_pytest_style_tests


class PythonRuntimeAsync:
    def _can_run_pytest(self) -> bool:
        return shutil.which("pytest") is not None or importlib.util.find_spec("pytest") is not None

    def _pytest_tests_dir(self, run_command: str) -> str:
        try:
            parts = shlex.split(run_command or "", posix=False)
        except ValueError:
            parts = (run_command or "").split()
        for part in parts:
            normalized = part.strip("'\"").replace("\\", "/")
            if normalized in {"tests", "tests/", ".codeteam_qa/tests", ".codeteam_qa/tests/"}:
                return normalized.rstrip("/")
            if normalized.startswith(".codeteam_qa/tests/"):
                return ".codeteam_qa/tests"
        return "tests"

    def _is_test_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        return normalized.startswith("tests/") or normalized.startswith(".codeteam_qa/tests/")

    async def run_tests(self, repo_root: str, run_command: str) -> Dict[str, Any]:
        if "pytest" in run_command and not self._can_run_pytest():
            return await asyncio.to_thread(run_pytest_style_tests, repo_root, self._pytest_tests_dir(run_command))
        try:
            proc = await asyncio.create_subprocess_shell(
                run_command,
                cwd=Path(repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out_bytes, err_bytes = await proc.communicate()
            out = (out_bytes or b"").decode("utf-8", errors="ignore")
            err = (err_bytes or b"").decode("utf-8", errors="ignore")
            output = out + "\n" + err
            success = proc.returncode == 0
            failures = self._parse_failures(output)
            return {"success": success, "output": output, "failures": failures}
        except asyncio.TimeoutError:
            return {"success": False, "output": "TIMEOUT", "failures": [{"file_path":"", "message":"timeout","stack":""}]}

    def _parse_failures(self, text: str) -> List[Dict[str, str]]:
        buf = []
        for ln in text.splitlines():
            if ln.startswith("E   ") or "FAILED" in ln or "ERROR at" in ln or ln.startswith("Traceback"):
                buf.append(ln)
        stack = "\n".join(buf)
        if not stack:
            return []

        path_matches = []
        for line in buf:
            for match in re.findall(r"([A-Za-z0-9_./\\-]+\.py)", line):
                path_matches.append(match.replace("\\", "/"))

        source_paths = []
        test_paths = []
        for match in path_matches:
            if self._is_test_path(match):
                if match not in test_paths:
                    test_paths.append(match)
            else:
                if match not in source_paths:
                    source_paths.append(match)

        failures = []
        if source_paths:
            for source_path in source_paths:
                failures.append(
                    {
                        "file_path": source_path,
                        "source_file": source_path,
                        "test_file": test_paths[0] if test_paths else "",
                        "message": "test failure",
                        "stack": stack,
                    }
                )
            return failures

        test_file = test_paths[0] if test_paths else ""
        return [
            {
                "file_path": test_file,
                "source_file": "",
                "test_file": test_file,
                "message": "test failure",
                "stack": stack,
            }
        ]
