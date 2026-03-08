# runtime_adapters/python_runtime_async.py
from __future__ import annotations
import asyncio
import importlib.util
import shutil
from typing import Dict, Any, List
from pathlib import Path

from runtime_adapters.pytest_fallback import run_pytest_style_tests


class PythonRuntimeAsync:
    def _can_run_pytest(self) -> bool:
        return shutil.which("pytest") is not None or importlib.util.find_spec("pytest") is not None

    async def run_tests(self, repo_root: str, run_command: str) -> Dict[str, Any]:
        if "pytest" in run_command and not self._can_run_pytest():
            return await asyncio.to_thread(run_pytest_style_tests, repo_root)
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
        failures = []
        buf = []
        for ln in text.splitlines():
            if ln.startswith("E   ") or "FAILED" in ln or "ERROR at" in ln or ln.startswith("Traceback"):
                buf.append(ln)
        stack = "\n".join(buf)
        for ln in buf:
            if ".py" in ln and ":" in ln:
                frag = ln.strip().split(":")[0]
                if frag.endswith(".py"):
                    failures.append({"file_path": frag, "message": "test failure", "stack": stack})
        if not failures and stack:
            failures.append({"file_path": "", "message": "test failure", "stack": stack})
        return failures
