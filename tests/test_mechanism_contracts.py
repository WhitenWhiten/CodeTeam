import copy
from types import SimpleNamespace
import pytest
from core.llm import LLMClient
from core.schemas import validate_sds
from utils.sds_normalizer import normalize_sds_candidate


def sample():
    return LLMClient(SimpleNamespace(provider="mock"))._mock_sds()


def test_semantic_contradictions_are_rejected():
    for mutation in ("signature", "duplicate", "framework", "runtime", "alias"):
        s = sample()
        fn = s["file_specs"][0]["interfaces"]["functions"][0]
        if mutation == "signature": fn["signature"] = "def other():"
        if mutation == "duplicate": s["file_specs"][0]["interfaces"]["functions"].append(copy.deepcopy(fn))
        if mutation == "framework": s["tech_stack"]["test_framework"] = "unittest"
        if mutation == "runtime": s["tech_stack"]["runtime"] = "node20"
        if mutation == "alias": s["files"] = []
        with pytest.raises(ValueError): validate_sds(s)


def test_normalization_is_versioned_and_idempotent():
    s = sample(); s["files"] = s.pop("file_specs")
    normalized = normalize_sds_candidate(s)
    assert normalized["schema_version"] == "1.0"
    assert "files->file_specs" in normalized["normalization_log"]
    assert normalize_sds_candidate(normalized) == normalized


def test_implementation_enforces_signature_and_preserves_helpers():
    from core.interface_contracts import validate_implementation, validate_import_contract
    import ast
    interface = {"functions": [{"name": "f", "signature": "async def f(x: int, *, size=2) -> int:"}], "classes": []}
    for code in ("def f(): return 1", "async def f(x: int, size=2) -> int: return x", "async def f(x: int, *, size=3) -> int: return x"):
        with pytest.raises(ValueError): validate_implementation(code, interface)
    validate_implementation("async def f(x: int, *, size=2) -> int: return x\ndef _helper(): pass", interface)
    with pytest.raises(ValueError, match="Undeclared"):
        validate_import_contract(ast.parse("from provider import f"), "consumer.py", ["provider.py", "consumer.py"], [])
    report = validate_import_contract(ast.parse("import importlib\nimportlib.import_module(name)"), "consumer.py", ["consumer.py"], [])
    assert report["dynamic_unknown"]
