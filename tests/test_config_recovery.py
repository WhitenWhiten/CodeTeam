import asyncio
import json
from pathlib import Path
import pytest
from app.bootstrap import bootstrap
from app.config import SystemConfig, load_config
from app.main import main
from core.contracts import RunStatus
from orchestrator.workflow import MultiAgentCodegenWorkflow
from utils.run_artifacts import RunArtifacts


def test_json_environment_and_cli_precedence_and_validation(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"architects": 2, "llm": {"model": "file-model"}, "git": {"enabled": False}}))
    monkeypatch.setenv("CODETEAM_ARCHITECTS", "3")
    monkeypatch.setenv("CODETEAM_LLM_MODEL", "env-model")
    cfg = load_config(str(path), {"architects": 1})
    assert cfg.architects == 1 and cfg.llm.model == "env-model" and not cfg.git.enabled
    monkeypatch.setenv("CODETEAM_ARCHITECTS", "-1")
    with pytest.raises(ValueError):
        load_config(str(path))
    path.write_text('{"typo": 1}')
    with pytest.raises(ValueError):
        load_config(str(path))


def interrupted_run(tmp_path):
    cfg = SystemConfig(workspace=str(tmp_path / "workspace"), artifacts_dir=str(tmp_path / "artifacts"), architects=1, max_model_calls=4)
    cfg.git.enabled = False
    first = MultiAgentCodegenWorkflow(bootstrap(cfg)).run_sync(cfg.user_question)
    assert first.status == RunStatus.BUDGET_EXHAUSTED
    checkpoint = json.loads((Path(cfg.artifacts_dir) / "checkpoint.json").read_text())
    assert checkpoint["completed"] == ["shop/catalog.py"]
    return cfg, first, checkpoint


def test_resume_skips_completed_generation_and_preserves_usage(tmp_path):
    cfg, first, checkpoint = interrupted_run(tmp_path)
    before = (Path(first.repo_root) / "shop/catalog.py").read_bytes()
    cfg.resume_from = cfg.artifacts_dir
    cfg.max_model_calls = 20
    ctx = bootstrap(cfg)
    result = MultiAgentCodegenWorkflow(ctx).run_sync(cfg.user_question)
    assert result.success, result.reason
    assert result.repo_root == first.repo_root
    assert (Path(result.repo_root) / "shop/catalog.py").read_bytes() == before
    assert result.usage["calls"] == 6
    assert len(ctx.llm.usage.records) == 2
    assert result.usage["total_tokens"] > first.usage["total_tokens"]
    calls = sorted((Path(cfg.artifacts_dir) / "model_calls").glob("*.json"))
    assert len(calls) == 6
    events = [json.loads(line) for line in (Path(cfg.artifacts_dir) / "events.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "resume" for event in events)


def test_resume_rejects_source_changes_without_replacing_checkpoint(tmp_path):
    cfg, first, checkpoint = interrupted_run(tmp_path)
    checkpoint_path = Path(cfg.artifacts_dir) / "checkpoint.json"
    original = checkpoint_path.read_bytes()
    (Path(first.repo_root) / "shop/catalog.py").write_text("USER_EDIT = True")
    cfg.resume_from = cfg.artifacts_dir
    cfg.max_model_calls = 20
    result = MultiAgentCodegenWorkflow(bootstrap(cfg)).run_sync(cfg.user_question)
    assert result.status == RunStatus.ERROR and "source changed" in result.reason
    assert checkpoint_path.read_bytes() == original


def test_artifact_lock_rejects_concurrent_process_ownership(tmp_path):
    first, second = RunArtifacts(str(tmp_path)), RunArtifacts(str(tmp_path))
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another process"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_context_reuse_cannot_overwrite_a_completed_run(tmp_path):
    cfg = SystemConfig(workspace=str(tmp_path), architects=1)
    cfg.git.enabled = False
    ctx = bootstrap(cfg)
    first = MultiAgentCodegenWorkflow(ctx).run_sync(cfg.user_question)
    assert first.success
    saved = (ctx.artifacts.root / "checkpoint.json").read_bytes()
    second = MultiAgentCodegenWorkflow(ctx).run_sync(cfg.user_question)
    assert second.status == RunStatus.ERROR and "explicitly resume" in second.reason
    assert (ctx.artifacts.root / "checkpoint.json").read_bytes() == saved


def test_cli_runs_and_resumes_without_new_model_calls(tmp_path, capsys):
    artifacts = tmp_path / "artifacts"
    assert main(["--workspace", str(tmp_path / "workspace"), "--artifacts-dir", str(artifacts), "--architects", "1", "--no-git"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["--resume", str(artifacts)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["repo_root"] == first["repo_root"]
    assert second["usage"] == first["usage"]
    assert main(["--config", str(tmp_path / "missing.json")]) == 2
