"""Effective runtime policy and verified experiment expectations."""

def manifest(cfg):
    return {"version":1,"mechanisms":cfg.mechanisms.model_dump(),"architects":cfg.architects,
            "duplicate_policy":cfg.duplicate_candidate_policy,"git_commits":cfg.git.enabled,
            "git_branches":cfg.git.enabled and cfg.git.branches,"allocation":cfg.developer_allocation.model_dump(),
            "context":cfg.context.model_dump(),"rag":cfg.rag.model_dump(),"max_qa_repairs":cfg.max_rounds,
            "max_file_requeues":cfg.max_file_requeues,"sds_contract":"enforced",
            "workspace_policy":"shared_worktree_serialized_writes","qa_disabled_status":"generated_unverified"}


VARIANT_EXPECTATIONS={
    "no_competition":{"architects":1}, "no_diversity":{"mechanisms.architect_diversity":False},
    "no_cto":{"mechanisms.cto_selection":False}, "fixed_team":{"developer_allocation.dynamic_enabled":False},
    "no_ownership":{"mechanisms.ownership":"round_robin"}, "no_dependency_scheduling":{"mechanisms.dependency_scheduling":False},
    "no_requeue":{"mechanisms.dependent_requeue":False}, "no_live_briefs":{"mechanisms.live_briefs":False},
    "full_context":{"mechanisms.context_mode":"full"}, "no_branches":{"git.branches":False},
    "no_git":{"git.enabled":False}, "no_qa":{"mechanisms.qa_enabled":False},
    "no_qa_repair":{"mechanisms.qa_repair":False}, "no_progressive_qa":{"mechanisms.progressive_qa":False},
    "no_rag":{"rag.enabled":False}}


def validate_expectations(cfg,variant,declared):
    standard=VARIANT_EXPECTATIONS.get(variant,{})
    if any(key in standard and value!=standard[key] for key,value in declared.items()):
        raise ValueError("Declared expectations contradict the named mechanism variant")
    expected={**standard,**declared}
    if variant in {"no_sds","without_sds","w/o_sds"}:
        raise ValueError("Removing SDS requires an independent freeform adapter; this runtime enforces SDS")
    if variant!="full" and variant not in VARIANT_EXPECTATIONS and not declared:
        raise ValueError("Custom variant needs explicit mechanism_expectations; a label is not an intervention")
    for path,value in expected.items():
        actual=cfg.model_dump()
        for key in path.split("."):
            if not isinstance(actual,dict) or key not in actual: raise ValueError("Unknown mechanism expectation: "+path)
            actual=actual[key]
        if actual!=value: raise ValueError(f"Variant expectation mismatch: {path}={actual!r}, expected {value!r}")
    return expected
