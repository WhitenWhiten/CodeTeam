from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from actions.run_tests import RunTestsAction
from core.models import FileSpec, FuncBrief, SDS, DevAssignment
from runtime_adapters.python_runtime import PythonRuntime
from utils.failure_routing import build_fix_suggestions


def _sample_sds() -> SDS:
    return SDS(
        id="sds-test",
        problem="routing",
        tech_stack={"language": "python", "frameworks": [], "runtime": "python", "test_framework": "pytest"},
        repo_structure=[],
        file_specs=[
            FileSpec(
                path="main.py",
                responsibilities="dependent entrypoint",
                interfaces={"functions": [FuncBrief(name="checkout_total", signature="def checkout_total(items):")], "classes": []},
                dependencies=["shop/catalog.py"],
            ),
            FileSpec(
                path="shop/catalog.py",
                responsibilities="catalog provider",
                interfaces={"functions": [FuncBrief(name="get_price", signature="def get_price(name):")], "classes": []},
                dependencies=[],
            ),
        ],
        dev_plan=[
            DevAssignment(developer_id="Dev-1", file_paths=["main.py"]),
            DevAssignment(developer_id="Dev-2", file_paths=["shop/catalog.py"]),
        ],
    )


class QATempTests(unittest.TestCase):
    def test_temp_qa_tests_are_cleaned_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample_qa_module.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
            tests = {
                "tests/test_sample_qa_module.py": "from sample_qa_module import answer\n\n\ndef test_answer():\n    assert answer() == 42\n",
            }

            result = asyncio.run(
                RunTestsAction().run(
                    repo_root=str(root),
                    run_command="pytest -q",
                    runtime_adapter=PythonRuntime(),
                    tests=tests,
                    setup_commands=["python -m pip --version"],
                )
            )

            self.assertTrue(result["success"], result["output"])
            self.assertEqual(result["setup_commands"][0]["status"], "success")
            self.assertIn("SETUP success: python -m pip --version", result["output"])
            self.assertFalse((root / ".codeteam_qa").exists())
            self.assertFalse((root / "tests" / "test_sample_qa_module.py").exists())
            self.assertIn(".codeteam_qa/tests", result["qa_run_command"]["effective"])

    def test_disallowed_setup_command_blocks_test_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                RunTestsAction().run(
                    repo_root=tmp,
                    run_command="pytest -q",
                    runtime_adapter=PythonRuntime(),
                    tests={"tests/test_never_runs.py": "def test_never_runs():\n    assert True\n"},
                    setup_commands=["echo unsafe"],
                )
            )

            self.assertFalse(result["success"])
            self.assertEqual(result["setup_commands"][0]["status"], "blocked")
            self.assertIn("SETUP blocked: echo unsafe", result["output"])


class FailureRoutingDiagnosticsTests(unittest.TestCase):
    def test_missing_public_api_routes_to_source_owner_not_dependent_traceback(self):
        failure = {
            "file_path": "main.py",
            "source_file": "main.py",
            "test_file": ".codeteam_qa/tests/test_checkout.py",
            "message": "ImportError: cannot import name 'get_price' from 'shop.catalog'",
            "stack": (
                "Traceback\n"
                "  File \"main.py\", line 1, in <module>\n"
                "    from shop.catalog import get_price\n"
                "ImportError: cannot import name 'get_price' from 'shop.catalog'\n"
            ),
        }
        file_owner = {"main.py": "Dev-1", "shop/catalog.py": "Dev-2"}

        suggestions = build_fix_suggestions([failure], file_owner, sds=_sample_sds())

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["dev_id"], "Dev-2")
        self.assertEqual(suggestions[0]["file_path"], "shop/catalog.py")
        self.assertEqual(suggestions[0]["suspected_source_files"], ["shop/catalog.py"])
        self.assertTrue(suggestions[0]["public_api_changed"])
        self.assertEqual(suggestions[0]["affected_dependents"], ["main.py"])

    def test_unknown_failure_does_not_fan_out_to_all_source_files(self):
        failure = {
            "file_path": ".codeteam_qa/tests/test_smoke.py",
            "source_file": "",
            "message": "assertion failed",
            "stack": "AssertionError: value was false",
        }
        file_owner = {"main.py": "Dev-1", "shop/catalog.py": "Dev-2", "shop/cart.py": "Dev-3"}

        suggestions = build_fix_suggestions([failure], file_owner, sds=_sample_sds())

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["category"], "unknown")
        self.assertEqual(suggestions[0]["suspected_source_files"], [])
        self.assertEqual(suggestions[0]["minimal_repair_scope"], [])
        self.assertFalse(suggestions[0]["requeue"])


if __name__ == "__main__":
    unittest.main()
