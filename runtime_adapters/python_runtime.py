# runtime_adapters/python_runtime.py
from __future__ import annotations
import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, Any, List

class PythonRuntime:
    def run_tests(self, repo_root: str, run_command: str) -> Dict[str, Any]:
        # 进入仓库目录执行pytest
        cwd = Path(repo_root)
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
        # 简化的pytest失败解析：抓取 "E   " 段落以及 "Traceback" 文件路径
        failures = []
        current = {"file_path": "", "message": "", "stack": ""}
        lines = text.splitlines()
        buf = []
        for ln in lines:
            if ln.startswith("E   ") or "FAILED" in ln or "ERROR at" in ln or ln.startswith("Traceback"):
                buf.append(ln)
        stack = "\n".join(buf)
        # 尝试提取文件路径 tests/或源文件路径
        for ln in buf:
            if ".py" in ln and ":" in ln:
                # 例如 path/to/file.py:123:
                frag = ln.strip().split(":")[0]
                if frag.endswith(".py"):
                    failures.append({"file_path": frag, "message": "test failure", "stack": stack})
        if not failures and stack:
            failures.append({"file_path": "", "message": "test failure", "stack": stack})
        return failures