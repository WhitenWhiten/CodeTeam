from core.workload import annotate_workload, workload_report
from orchestrator.scheduler import DependencyScheduler


def test_workload_and_queued_ownership_are_recomputable():
    s={"file_specs":[{"path":p,"interfaces":{"functions":[],"classes":[]},"dependencies":[]} for p in ["a.py","b.py"]],
       "dev_plan":[{"developer_id":"A","file_paths":["a.py"]},{"developer_id":"B","file_paths":["b.py"]}]}
    s=annotate_workload(s)
    scheduler=DependencyScheduler(s["file_specs"],s["dev_plan"],max_concurrent=1)
    assert len(scheduler.dispatch_ready())==1
    assert scheduler.owner_for("b.py")=="B"
    report=workload_report(s,scheduler,1)
    assert report["team_size"]==2 and sum(r["effort"] for r in report["owners"])==2
    assert report["warnings"]
