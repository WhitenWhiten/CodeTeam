# runtime_adapters/python_runtime.py
from __future__ import annotations
import importlib.util
import re
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, List

from runtime_adapters.pytest_fallback import run_pytest_style_tests


class PythonRuntime:
    def _can_run_pytest(self) -> bool:
        return shutil.which("pytest") is not None or importlib.util.find_spec("pytest") is not None

    def run_tests(self, repo_root: str, run_command: str) -> Dict[str, Any]:
        # 进入仓库目录执行pytest
        cwd = Path(repo_root)
        if "pytest" in run_command and not self._can_run_pytest():
            return run_pytest_style_tests(str(cwd))
        try:
            proc = subprocess.run(
                run_command, shell=True, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600
            )
            success = proc.returncode == 0
            output = proc.stdout + "\n" + proc.stderr
            failures = self._parse_failures(output)
            return {"success": success, "output": output, "failures": failures}
        except subprocess.TimeoutExpired as e:
            return {"success": False, "output": f"TIMEOUT: {e}", "failures": [{"file_path": "", "message": "timeout", "stack": ""}]}

    def _parse_failures(self, text: str) -> List[Dict[str, str]]:
        buf = []
        for line in text.splitlines():
            if line.startswith("E   ") or "FAILED" in line or "ERROR at" in line or line.startswith("Traceback"):
                buf.append(line)
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
            if match.startswith("tests/"):
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
