from utils.failure_routing import build_fix_suggestions, _build_sds_context
from orchestrator.scheduler import merge_repair_payload


def test_repair_payload_preserves_all_failures_and_evidence():
    rows = {}
    merge_repair_payload(rows, "a.py", {"message": "first"}, {"category": "assertion"})
    merge_repair_payload(rows, "a.py", {"message": "second"}, {"category": "syntax"})
    assert [x["message"] for x in rows["a.py"]["issues"]["failures"]] == ["first", "second"]
    assert len(rows["a.py"]["issues"]["routing_evidence"]) == 2


def test_diagnostics_require_actual_source_evidence():
    failures = [{"source_file": "a.py", "message": "bad"}]
    fix = build_fix_suggestions(failures, {"a.py": "d"})[0]
    assert fix["diagnostics"]["structural_validity"]["status"] == "not_evaluated"
    fix = build_fix_suggestions(failures, {"a.py": "d"}, source_reader=lambda p: "def bad(:")[0]
    assert fix["diagnostics"]["structural_validity"]["status"] == "failed"


def test_ambiguous_provider_is_not_arbitrarily_selected():
    specs = [{"path": p, "interfaces": {"functions": [{"name": "foo", "signature": "def foo():"}]}, "dependencies": []} for p in ("a.py", "b.py")]
    fix = build_fix_suggestions([{"message": "cannot import name 'foo'"}], {"a.py": "d", "b.py": "e"}, {"file_specs": specs})[0]
    assert fix["category"] == "unknown" and not fix["requeue"]
