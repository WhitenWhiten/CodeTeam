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
    repo=RepoManager(str(tmp_path),{"main.py"},{},git_enabled=False)
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
