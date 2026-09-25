import shutil
import subprocess
from pathlib import Path
import pytest
from app.bootstrap import bootstrap
from app.config import SystemConfig
from core.repo_manager import RepoManager
from orchestrator.workflow import MultiAgentCodegenWorkflow


def repository(tmp_path, git=False):
    repo = RepoManager(str(tmp_path), {"a.py", "b.py"}, {"A": {"a.py"}, "B": {"b.py"}}, git_enabled=git)
    repo.init_structure(["a.py", "b.py"])
    return repo


def test_ownership_is_required_even_for_globally_allowed_files(tmp_path):
    repo = repository(tmp_path)
    with pytest.raises(PermissionError, match="owned"):
        repo.write_file("b.py", "broken", agent_id="A")
    with pytest.raises(PermissionError):
        repo.write_file("tests/undeclared.py", "broken", agent_id="QA")
    assert repo.read_file("b.py") == ""


@pytest.mark.parametrize("path", ["../outside.py", ".GIT/config", "a.py:stream", "CON.txt"])
def test_path_aliases_and_traversal_rejected(tmp_path, path):
    repo = repository(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        repo.read_file(path)


def test_initialization_preserves_existing_content_and_rejects_escape(tmp_path):
    repo = repository(tmp_path)
    repo.write_file("a.py", "A = 1", "A")
    repo.init_structure(["a.py", "b.py"])
    assert repo.read_file("a.py") == "A = 1"
    with pytest.raises(ValueError):
        repo.init_structure({"../escape": {}})


@pytest.mark.skipif(not shutil.which("git"), reason="git required")
def test_repeat_developer_branch_uses_latest_integrated_sources(tmp_path):
    repo = repository(tmp_path, git=True)
    for agent, path, code in [("A", "a.py", "A = 1"), ("B", "b.py", "B = 2"), ("A", "a.py", "A = 3")]:
        repo.checkout_agent_branch(agent)
        if code == "A = 3":
            assert repo.read_file("b.py") == "B = 2"
        repo.write_file(path, code, agent)
        repo.commit_file(path, {}, agent)
    assert repo._current_branch() == "main"
    assert repo.read_file("a.py") == "A = 3"
    assert repo.read_file("b.py") == "B = 2"
    assert repo._git("status", "--porcelain").stdout == ""


@pytest.mark.skipif(not shutil.which("git"), reason="git required")
def test_git_add_failure_is_reported(tmp_path, monkeypatch):
    repo = repository(tmp_path, git=True)
    original = repo._git
    def fail(*args, **kwargs):
        if args[0] == "add":
            raise subprocess.CalledProcessError(1, "git add")
        return original(*args, **kwargs)
    monkeypatch.setattr(repo, "_git", fail)
    with pytest.raises(subprocess.CalledProcessError):
        repo.commit_file("a.py", {}, "A")


@pytest.mark.skipif(not shutil.which("git"), reason="git required")
def test_full_workflow_with_git_has_clean_integrated_tree(tmp_path):
    cfg = SystemConfig(workspace=str(tmp_path), architects=1)
    result = MultiAgentCodegenWorkflow(bootstrap(cfg)).run_sync(cfg.user_question)
    assert result.success, result.reason
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=result.repo_root) == b""
    assert subprocess.check_output(["git", "branch", "--show-current"], cwd=result.repo_root).strip() == b"main"
