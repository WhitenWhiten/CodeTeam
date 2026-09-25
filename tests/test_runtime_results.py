import asyncio
import sys
from pathlib import Path

from runtime_adapters.python_runtime import PythonRuntime
from runtime_adapters.python_runtime_async import PythonRuntimeAsync
from runtime_adapters.process import run_process


def test_pytest_module_works_without_console_launcher_and_reports_each_test(tmp_path):
    (tmp_path / "test_example.py").write_text("def test_ok(): assert True\ndef test_bad(): assert False\n")
    result = PythonRuntime().run_tests(str(tmp_path), "pytest -q")
    assert result["counts"]["passed"] == 1
    assert result["counts"]["failed"] == 1
    assert "test_bad" in result["failures"][0]["nodeid"]
    assert result["command"][:3] == [sys.executable, "-m", "pytest"]


def test_no_tests_and_collection_error_are_not_success(tmp_path):
    runner = PythonRuntime()
    assert runner.run_tests(str(tmp_path), "pytest -q")["status"] == "no_tests"
    (tmp_path / "test_broken.py").write_text("import missing_codeteam_dependency\n")
    result = runner.run_tests(str(tmp_path), "pytest -q")
    assert result["status"] == "collection_error"
    assert result["failures"]


def test_timeout_kills_child_before_it_can_write(tmp_path):
    async def check():
        marker = tmp_path / "should_not_exist"
        script = "import time; from pathlib import Path; time.sleep(2); Path('should_not_exist').write_text('bad')"
        result = await run_process([sys.executable, "-c", script], tmp_path, timeout=0.1)
        assert result["timed_out"]
        assert result["returncode"] != 0
        assert not marker.exists()
    asyncio.run(check())


def test_async_adapter_reports_passed_test(tmp_path):
    (tmp_path / "test_good.py").write_text("def test_ok(): assert 1 + 1 == 2\n")
    result = asyncio.run(PythonRuntimeAsync().run_tests(str(tmp_path), "python -m pytest -q"))
    assert result["success"] and result["counts"]["passed"] == 1
