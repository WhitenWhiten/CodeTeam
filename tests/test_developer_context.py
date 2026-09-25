import asyncio
from types import SimpleNamespace

import pytest

from actions.generate_code import GenerateCodeAction
from core.ast_utils import to_brief
from core.brief_manager import BriefManager
from core.repo_manager import RepoManager
from roles.developer_worker_async import DeveloperWorkerAsync


SPEC = {"path": "a.py", "responsibilities": "answer", "interfaces": {"functions": [{"name": "answer", "signature": "def answer() -> int:"}], "classes": []}, "dependencies": []}


def test_repair_receives_source_and_full_change_information(tmp_path):
    repo = RepoManager(str(tmp_path), {"a.py"}, {"Dev": {"a.py"}}, git_enabled=False)
    original = "def answer() -> int:\n    return 0\n\ndef helper():\n    return 9\n"
    repo.write_file("a.py", original, "Dev")
    class LLM:
        async def text(self, prompt):
            assert original in prompt
            for value in ["changed meaning", "must be positive", "breaks callers", "upstream changed"]:
                assert value in prompt
            return original.replace("return 0", "return 42")
    briefs = {"b.py": {"latest_update_reason": {"rationale": "changed meaning"},
                           "invariants": ["must be positive"], "compatibility_note": "breaks callers"}}
    asyncio.run(GenerateCodeAction().run(SPEC, briefs, LLM(), repo, "Dev", {"reason": "upstream changed"}))
    scope = {}
    exec(repo.read_file("a.py"), scope)
    assert scope["answer"]() == 42 and scope["helper"]() == 9


def test_invalid_replacement_does_not_destroy_existing_file(tmp_path):
    repo = RepoManager(str(tmp_path), {"a.py"}, {"Dev": {"a.py"}}, git_enabled=False)
    repo.write_file("a.py", "def answer(): return 1", "Dev")
    class LLM:
        async def text(self, prompt):
            return "def broken("
    with pytest.raises(ValueError, match="Invalid generation"):
        asyncio.run(GenerateCodeAction().run(SPEC, {}, LLM(), repo, "Dev"))
    assert repo.read_file("a.py") == "def answer(): return 1"


def test_signature_preserves_defaults_async_and_keyword_only_arguments():
    brief = to_brief("async def f(x: int = 1, *, y: str = 'ok') -> bool:\n    return True")
    sig = brief["functions"][0]["signature"]
    assert sig.startswith("async def f") and "x: int=1" in sig and "*, y:" in sig and "-> bool" in sig


def test_same_owner_symbol_dependency_is_in_context():
    async def check():
        b = dict(SPEC, path="b.py")
        a = dict(SPEC, dependencies=["b.py::answer"])
        manager = BriefManager()
        manager.update_brief("b.py", {"functions": [], "classes": [], "compatibility_note": "fresh"})
        worker = DeveloperWorkerAsync("Dev", ["a.py", "b.py"], {"a.py": a, "b.py": b}, None, None, manager, None)
        assert (await worker._collect_briefs(a))["b.py"]["compatibility_note"] == "fresh"
    asyncio.run(check())
