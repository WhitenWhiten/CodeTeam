from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from runtime_adapters.process import run_process


def command_args(command):
    parts = [p.strip("\"'") for p in shlex.split(command, posix=os.name != "nt")]
    if not parts or any(p in {"&&", ";", "|", "||", ">", "<"} for p in parts):
        raise ValueError("Expected a single pytest or pip command")
    return parts


def python_module_args(command, python_executable=sys.executable, setup=False):
    parts = command_args(command)
    program = Path(parts[0]).stem.lower()
    if program in {"pytest", "pip", "pip3"}:
        module = "pip" if program.startswith("pip") else "pytest"
        args = parts[1:]
    elif (program in {"python", "python3", "python3.11", "python3.12", "python3.13"}
          or str(Path(parts[0])) == str(Path(python_executable))) and len(parts) >= 3 and parts[1] == "-m":
        module, args = parts[2], parts[3:]
    else:
        raise ValueError("Only Python module pytest/pip commands are supported")
    if module not in ({"pip", "pytest"} if setup else {"pytest"}):
        raise ValueError(f"Unsupported module: {module}")
    if module == "pip" and (not args or args[0] not in {"install", "--version"}):
        raise ValueError("Only pip install and pip --version are supported")
    return [python_executable, "-m", module, *args]


class RuntimeBase:
    def __init__(self, python_executable=None, timeout=120):
        self.python_executable = python_executable or sys.executable
        self.timeout = timeout

    def _parse_failures(self, text):
        paths = re.findall(r"([A-Za-z0-9_./\\-]+\.py)(?::\d+|[\"'])", text)
        source = next((p.replace("\\", "/") for p in reversed(paths)
                       if "tests/" not in p.replace("\\", "/") and "test_" not in Path(p).name), "")
        return [{"file_path": source, "source_file": source, "message": "test failure",
                 "stack": text, "category": "test_failure"}] if text.strip() else []

    async def run_tests_async(self, repo_root, run_command):
        base = {"success": False, "failures": [], "counts": {"collected": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}}
        try:
            argv = python_module_args(run_command, self.python_executable)
        except ValueError as exc:
            return dict(base, status="environment_error", output=str(exc),
                        failures=[{"category": "environment_error", "message": str(exc), "file_path": "", "stack": ""}])
        if any(arg.startswith("--junit") for arg in argv):
            return dict(base, status="environment_error", output="CodeTeam manages the JUnit report location")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env.pop("PYTEST_ADDOPTS", None)
        root = str(Path(repo_root).resolve())
        env["PYTHONPATH"] = os.pathsep.join([root, str(Path(root) / "src")])
        with tempfile.TemporaryDirectory(prefix="codeteam-pytest-") as tmp:
            report = Path(tmp) / "junit.xml"
            argv += [f"--junitxml={report}", "-o", "junit_family=xunit1", "-p", "no:cacheprovider"]
            try:
                proc = await run_process(argv, root, self.timeout, env)
            except OSError as exc:
                return dict(base, status="environment_error", output=str(exc))
            base.update(proc)
            base["command"] = argv
            if proc["timed_out"]:
                base.update(status="timeout", failures=[{"category": "timeout", "file_path": "",
                            "message": "QA process timed out", "stack": proc["output"]}])
                return base
            if report.exists():
                try:
                    cases = list(ET.parse(report).getroot().iter("testcase"))
                except ET.ParseError:
                    cases = []
                for case in cases:
                    base["counts"]["collected"] += 1
                    issue = case.find("failure")
                    category = "test_failure"
                    if issue is None:
                        issue = case.find("error")
                        category = "collection_error" if proc["returncode"] == 2 else "test_error"
                    if issue is not None:
                        kind = "failed" if issue.tag == "failure" else "errors"
                        base["counts"][kind] += 1
                        stack = issue.text or ""
                        failure = self._parse_failures(stack)[0] if stack.strip() else {}
                        failure.update(message=issue.get("message", category), stack=stack, category=category,
                                       test_file=case.get("file", ""), nodeid=case.get("classname", "") + "::" + case.get("name", ""))
                        base["failures"].append(failure)
                    elif case.find("skipped") is not None:
                        base["counts"]["skipped"] += 1
                    else:
                        base["counts"]["passed"] += 1
            c = base["counts"]
            base["success"] = proc["returncode"] == 0 and c["passed"] > 0 and not (c["failed"] or c["errors"])
            base["status"] = ("passed" if base["success"] else "collection_error" if proc["returncode"] == 2
                              else "no_tests" if proc["returncode"] in {0, 5} and c["passed"] == 0
                              else "failed" if c["failed"] or c["errors"] else "environment_error")
            if not base["success"] and not base["failures"]:
                base["failures"] = [{"category": base["status"], "file_path": "", "message": base["status"], "stack": base["output"]}]
            return base
