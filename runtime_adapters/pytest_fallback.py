from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List


def _relative_path(path: str, repo_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return Path(path).as_posix()


def _guess_source_file(tb_exc: traceback.TracebackException, repo_root: Path) -> str:
    for frame in reversed(tb_exc.stack):
        rel = _relative_path(frame.filename, repo_root)
        if rel.endswith(".py") and not rel.startswith("tests/"):
            return rel
    for frame in reversed(tb_exc.stack):
        rel = _relative_path(frame.filename, repo_root)
        if rel.endswith(".py"):
            return rel
    return ""


def run_pytest_style_tests(repo_root: str) -> Dict[str, Any]:
    root = Path(repo_root).resolve()
    test_files = sorted(root.glob("tests/test_*.py"))
    if not test_files:
        return {"success": True, "output": "no tests discovered", "failures": []}

    original_sys_path = list(sys.path)
    sys.path.insert(0, str(root))
    failures: List[Dict[str, str]] = []
    output_lines: List[str] = []
    passed = 0
    failed = 0

    try:
        for test_file in test_files:
            rel_test = test_file.relative_to(root).as_posix()
            module_name = f"_codeteam_{test_file.stem}"
            sys.modules.pop(module_name, None)

            try:
                spec = importlib.util.spec_from_file_location(module_name, test_file)
                if spec is None or spec.loader is None:
                    raise ImportError(f"unable to load {rel_test}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as exc:
                tb_exc = traceback.TracebackException.from_exception(exc)
                failures.append(
                    {
                        "file_path": _guess_source_file(tb_exc, root) or rel_test,
                        "message": f"import failed for {rel_test}",
                        "stack": "".join(tb_exc.format()),
                    }
                )
                output_lines.append(f"FAILED {rel_test}::import")
                output_lines.extend(line.rstrip("\n") for line in tb_exc.format())
                failed += 1
                continue

            test_functions = [
                (name, fn)
                for name, fn in vars(module).items()
                if name.startswith("test_") and callable(fn)
            ]

            for test_name, test_func in test_functions:
                if inspect.signature(test_func).parameters:
                    failed += 1
                    message = f"unsupported pytest fixture signature in {rel_test}::{test_name}"
                    failures.append(
                        {"file_path": rel_test, "message": message, "stack": message}
                    )
                    output_lines.append(f"FAILED {rel_test}::{test_name}")
                    output_lines.append(message)
                    continue

                try:
                    test_func()
                    passed += 1
                    output_lines.append(f"PASSED {rel_test}::{test_name}")
                except Exception as exc:
                    tb_exc = traceback.TracebackException.from_exception(exc)
                    failures.append(
                        {
                            "file_path": _guess_source_file(tb_exc, root) or rel_test,
                            "message": f"test failed: {rel_test}::{test_name}",
                            "stack": "".join(tb_exc.format()),
                        }
                    )
                    output_lines.append(f"FAILED {rel_test}::{test_name}")
                    output_lines.extend(line.rstrip("\n") for line in tb_exc.format())
                    failed += 1
    finally:
        sys.path[:] = original_sys_path

    output_lines.append(f"{passed} passed, {failed} failed")
    return {"success": failed == 0, "output": "\n".join(output_lines), "failures": failures}
