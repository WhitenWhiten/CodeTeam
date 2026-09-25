"""Auditable CTO scoring contract."""
from core.dependencies import resolve_file_dependencies
CRITERIA = ("structural_validity", "interface_consistency", "implementability", "developer_plan")
CTO_DECISION_SCHEMA = {"type": "object", "required": ["evaluations"], "properties": {
    "evaluations": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["candidate_id", "scores", "rationale", "assumptions"], "properties": {
        "candidate_id": {"type": "string"}, "scores": {"type": "object", "required": list(CRITERIA), "properties": {k: {"type": "integer", "minimum": 0, "maximum": 2} for k in CRITERIA}, "additionalProperties": False},
        "rationale": {"type": "string"}, "assumptions": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}}
}, "additionalProperties": False}


def rank_candidates(result, candidates):
    import jsonschema
    jsonschema.validate(result, CTO_DECISION_SCHEMA)
    expected = {c["candidate_id"] for c in candidates}
    evaluations = result["evaluations"]
    ids = [r["candidate_id"] for r in evaluations]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("CTO must score every valid candidate exactly once")
    lookup = {r["candidate_id"]: r for r in evaluations}
    ranked = []
    for c in candidates:
        row = dict(lookup[c["candidate_id"]])
        dependencies = resolve_file_dependencies(c["sds"]["file_specs"], strict=True)
        fanout = {p: 0 for p in dependencies}
        for deps in dependencies.values():
            for path in deps: fanout[path] += 1
        row.update(total=sum(row["scores"].values()), assumption_count=len(set(row["assumptions"])),
                   maximum_fanout=max(fanout.values(), default=0), edge_count=sum(fanout.values()), source_index=c["source_index"])
        ranked.append(row)
    return sorted(ranked, key=lambda r: (-r["total"], r["assumption_count"], r["maximum_fanout"], r["edge_count"], r["source_index"]))
