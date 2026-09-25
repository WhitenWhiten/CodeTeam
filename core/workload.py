"""Coarse relative work units; not estimated wall time or token guarantees."""
from copy import deepcopy
from core.contracts import to_jsonable


def estimate(spec):
    if spec.get("workload"): return spec["workload"]
    interfaces=spec.get("interfaces",{})
    count=len(interfaces.get("functions",[]))+sum(1+len(c.get("methods",[])) for c in interfaces.get("classes",[]))
    return {"effort":1+count+len(spec.get("dependencies",[])), "source":"structural_heuristic",
            "rationale":"1 + declared functions/classes/methods + dependency references; relative units"}


def annotate_workload(sds):
    result=deepcopy(sds)
    for spec in result["file_specs"]: spec["workload"]=estimate(spec)
    return result


def workload_report(sds,scheduler,max_concurrent,remaining_calls=None):
    files={s["path"]:estimate(s) for s in to_jsonable(sds)["file_specs"]}
    owners=[]
    for owner in scheduler.owner_order:
        paths=[p for p in scheduler.files if scheduler.owner_by_file[p]==owner]
        owners.append({"owner":owner,"files":paths,"file_count":len(paths),"effort":sum(files[p]["effort"] for p in paths),
                       "dependency_chain_depth":max((scheduler.depth[p] for p in paths),default=0)})
    weights=[o["effort"] for o in owners if o["effort"]]
    warnings=[]
    if weights and max(weights)>2*min(weights): warnings.append("estimated_owner_load_ratio_over_two")
    if len(owners)>max_concurrent: warnings.append("team_exceeds_concurrent_slots_queued_without_reassignment")
    if remaining_calls is not None and remaining_calls<len(files): warnings.append("remaining_calls_below_one_generation_per_file")
    return {"unit":"relative_work_units", "file_estimates":files, "owners":owners,"team_size":len(owners),
            "max_concurrent":max_concurrent,"policy":"queue_preserve_ownership", "warnings":warnings,
            "dependency_edges":{p:sorted(v) for p,v in scheduler.dependencies.items()}}
