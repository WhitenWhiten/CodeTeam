import asyncio
from types import SimpleNamespace
import pytest
from core.qa_contracts import assert_preserves_tests
from core.llm import LLMClient
from core.repo_manager import RepoManager
from roles.qa_agent_async import QAAgentAsync
from utils.sds_parser import parse_sds


def test_progressive_qa_keeps_regressions_and_requirement_context(tmp_path):
    model=LLMClient(SimpleNamespace(provider="mock")); s=model._mock_sds()
    repo=RepoManager(str(tmp_path),{f["path"] for f in s["file_specs"]},{},git_enabled=False)
    repo.write_file("main.py","VALUE=1")
    qa=QAAgentAsync(model,repo,None,None,parse_sds(s),requirements="Must preserve an omitted feature")
    async def run():
        await qa.init_tests(s)
        initial=dict(qa.tests)
        await qa.refresh_tests({"main.py"},{},"batch")
        assert all(qa.tests[p]==v for p,v in initial.items())
        assert len(qa.history)==2
        assert "Must preserve an omitted feature" in qa._gen._build_prompt(s,{"requirements":qa.requirements})
    asyncio.run(run())


def test_qa_repair_cannot_weaken_existing_assertions():
    with pytest.raises(ValueError,match="assertions"):
        assert_preserves_tests({"tests/test_a.py":"def test_a(): assert f() == 2"},{"tests/test_a.py":"def test_a(): assert True"})


def test_incremental_test_filenames_are_collectible_and_fixtures_wait(tmp_path):
    model=LLMClient(SimpleNamespace(provider="mock")); s=model._mock_sds()
    repo=RepoManager(str(tmp_path),{f["path"] for f in s["file_specs"]},{},git_enabled=False)
    repo.write_file("main.py","VALUE=1")
    qa=QAAgentAsync(model,repo,None,None,parse_sds(s))
    class Generator:
        n=0
        async def run(self,**kwargs):
            self.n+=1
            return {"tests":{"tests/test_new.py":f"def test_value(): assert {self.n} > 0"},"run_command":"pytest -q"}
    qa._gen=Generator()
    async def run():
        await qa.init_tests(s)
        await qa.refresh_tests({"main.py"},{})
    asyncio.run(run())
    assert len(qa.tests)==2
    assert all(p.split("/")[-1].startswith("test_") for p in qa.tests)
    qa.tests={"tests/test_a.py":"from shop.catalog import get_price\ndef test_a(): assert get_price('apple')", "tests/conftest.py":"from main import checkout_total"}
    assert qa._ready_tests({"shop/catalog.py"})=={}
    assert "tests/conftest.py" in qa._ready_tests({"shop/catalog.py","shop/cart.py","main.py"})
