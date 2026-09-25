import asyncio, hashlib, json, subprocess
from pathlib import Path
import pytest
from app.config import SystemConfig
from app.bootstrap import bootstrap
from core.brief_manager import BriefManager
from core.contracts import RunStatus
from core.repo_manager import RepoManager
from actions.generate_code import GenerateCodeAction
from experiments.protocol import Condition
from orchestrator.scheduler import DependencyScheduler
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync


def test_ablation_labels_require_executed_policy():
    with pytest.raises(ValueError,match="mismatch"): Condition(condition_id="test",variant="no_qa")
    assert Condition(condition_id="test",variant="no_qa",config=SystemConfig(mechanisms={"qa_enabled":False}))
    with pytest.raises(ValueError,match="freeform"): Condition(condition_id="test",variant="no_sds")


def test_scheduling_switch_changes_dispatch_and_static_briefs_stay_frozen():
    specs=[{"path":"b.py","dependencies":["a.py"]},{"path":"a.py","dependencies":[]}]
    owners=[{"developer_id":"D","file_paths":["b.py","a.py"]}]
    assert DependencyScheduler(specs,owners).dispatch_ready()[0].file_path=="a.py"
    assert DependencyScheduler(specs,owners,dependency_scheduling=False).dispatch_ready()[0].file_path=="b.py"
    manager=BriefManager(live=False)
    manager.update_brief("a.py",{"functions":[],"source_hash":"first"})
    manager.update_brief("a.py",{"functions":[],"source_hash":"second"})
    assert manager.get_brief("a.py")["source_hash"]=="first"
    assert not manager.events[-1]["indexed"]
    manager.replay()
    assert manager.get_brief("a.py")["source_hash"]=="first"


def test_two_extra_brief_limit_is_enforced_before_writes(tmp_path):
    class Model:
        async def text(self,prompt): return '{"request_brief":"b.py"}'
    repo=RepoManager(str(tmp_path),{"a.py","b.py"},{"D":{"a.py"}},git_enabled=False)
    manager=BriefManager(); manager.update_brief("b.py",{"functions":[],"classes":[]})
    action=GenerateCodeAction(); action.brief_manager=manager; action.repo_files=["a.py","b.py"]
    spec={"path":"a.py","interfaces":{"functions":[],"classes":[]},"responsibilities":"small"}
    with pytest.raises(ValueError,match="request limit"):
        asyncio.run(action.run(spec,{},Model(),repo,"D"))
    assert not repo.exists("a.py")
    assert [e["status"] for e in manager.events if e["kind"]=="brief_request"]==["accepted","accepted","rejected_limit"]


def test_no_qa_and_no_cto_really_skip_calls_and_keep_commit_audit(tmp_path):
    cfg=SystemConfig(workspace=str(tmp_path/"w"),artifacts_dir=str(tmp_path/"a"),architects=1,
                     git={"enabled":True,"branches":False}, mechanisms={"qa_enabled":False,"cto_selection":False})
    ctx=bootstrap(cfg); result=asyncio.run(MultiAgentCodegenWorkflowAsync(ctx).run("Build a shop"))
    assert result.status==RunStatus.GENERATED_UNVERIFIED, result.reason
    counts=result.mechanisms["counters"]
    assert counts["cto_bypassed"]==1 and "cto_attempts" not in counts and "qa_test_generations" not in counts
    assert counts["developer_complete"]==3
    branches=subprocess.check_output(["git","branch","--format=%(refname:short)"],cwd=result.repo_root,text=True).splitlines()
    assert branches==["main"]
    journal=json.loads((ctx.artifacts.root/"interfaces/journal.json").read_text())
    accepted=[e for e in journal if e["kind"]=="publish" and e["brief"].get("commit_sha")]
    assert len(accepted)==3
    for event in accepted:
        code=subprocess.check_output(["git","show",event["brief"]["commit_sha"]+":"+event["file_path"]],cwd=result.repo_root)
        assert hashlib.sha256(code).hexdigest()==event["brief"]["source_hash"]


def test_full_flow_has_consistent_delivery_and_mechanism_evidence(tmp_path):
    cfg=SystemConfig(workspace=str(tmp_path/"w"),artifacts_dir=str(tmp_path/"a"),architects=1,git={"enabled":False})
    ctx=bootstrap(cfg); result=asyncio.run(MultiAgentCodegenWorkflowAsync(ctx).run("Build a shop"))
    assert result.success,result.reason
    assert result.qa["scope"]=="full" and result.qa["test_version"]>=1
    assert not result.incomplete["pending_files"] and not result.incomplete["awaiting_full_verification"]
    events=[json.loads(line) for line in (ctx.artifacts.root/"events.jsonl").read_text().splitlines()]
    dispatched={e["task"] for e in events if e.get("action")=="developer_dispatch"}
    complete={e["task"] for e in events if e.get("action")=="developer_complete"}
    assert dispatched==complete=={"main.py","shop/cart.py","shop/catalog.py"}
    assert json.loads((ctx.artifacts.root/"effective_mechanisms.json").read_text())["mechanisms"]["live_briefs"]
    assert (ctx.artifacts.root/"requirements/trace.json").exists()


@pytest.mark.parametrize("failure",["stale","commit"])
def test_rejected_write_never_publishes_an_accepted_brief(tmp_path, failure):
    from core.brief_manager import StaleBriefContext
    repo=RepoManager(str(tmp_path),{"a.py","b.py"},{"D":{"a.py"}},git_enabled=False)
    manager=BriefManager()
    manager.update_brief("b.py",{"functions":[],"source_hash":"before"})
    class Model:
        async def text(self,prompt):
            if failure=="stale": manager.update_brief("b.py",{"functions":[],"source_hash":"after"})
            return "VALUE=1"
    def commit_failure(*args,**kwargs): raise RuntimeError("simulated commit failure")
    if failure=="commit": repo.commit_file=commit_failure
    action=GenerateCodeAction(); action.brief_manager=manager
    spec={"path":"a.py","interfaces":{"functions":[],"classes":[]},"responsibilities":"small"}
    with pytest.raises(StaleBriefContext if failure=="stale" else RuntimeError):
        asyncio.run(action.run(spec,{"b.py":manager.get_brief("b.py")},Model(),repo,"D"))
    assert manager.get_brief("a.py") is None
    assert not any(e["kind"]=="publish" and e["file_path"]=="a.py" for e in manager.events)
    if failure=="stale": assert not repo.exists("a.py")
