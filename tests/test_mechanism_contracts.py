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


def test_delivery_rejects_unowned_source_and_accepts_explicit_static_rule(tmp_path):
    from core.delivery import check_delivery, initialize_static_files
    from core.repo_manager import RepoManager
    from utils.allowed_files import flatten_repo_structure
    s=sample(); s["repo_structure"].append({"path":"orphan.py","type":"file"})
    with pytest.raises(ValueError, match="producer"): validate_sds(s)
    s["file_rules"]=[{"path":"orphan.py","kind":"source","producer":"static","content":"VALUE = 1"}]
    validate_sds(s)
    repo=RepoManager(str(tmp_path),set(flatten_repo_structure(s["repo_structure"])),{},git_enabled=False)
    repo.init_structure(s["repo_structure"]); initialize_static_files(repo,s)
    report=check_delivery(repo,s)
    assert not report["success"]
    assert any(f["path"]=="main.py" for f in report["failures"])
    assert not any(f["path"].endswith("__init__.py") for f in report["failures"])


def test_literal_default_string_is_not_equivalent_to_number():
    from core.interface_contracts import validate_implementation
    with pytest.raises(ValueError,match="Default"):
        validate_implementation("def f(x=1): pass", {"functions":[{"name":"f","signature":"def f(x='1'):"}],"classes":[]})


def test_delivery_dependency_manifest_uses_declarations_not_mentions(tmp_path):
    from core.delivery import check_delivery
    from core.repo_manager import RepoManager
    s=sample()
    s["tech_stack"]["dependencies"]=["requests>=2"]
    s["file_specs"]=[]
    s["file_rules"]=[{"path":"requirements.txt","producer":"static","kind":"manifest","content":"requests>=2"},
                     {"path":"pyproject.toml","producer":"static","kind":"manifest","content":"[project]"}]
    repo=RepoManager(str(tmp_path),{"requirements.txt","pyproject.toml"},{},git_enabled=False)
    repo.write_file("requirements.txt","# requests>=2\nrequests-mock>=1\n")
    repo.write_file("pyproject.toml",'[project]\nname="requests"\n[build-system]\nrequires=["requests"]')
    assert not check_delivery(repo,s)["success"]
    repo.write_file("pyproject.toml",'[project]\ndependencies=["requests>=2"]')
    assert check_delivery(repo,s)["success"]
    repo.write_file("pyproject.toml","[broken")
    assert not check_delivery(repo,s)["success"]


def test_dependency_manifest_follows_planned_includes(tmp_path):
    from core.delivery import _manifest_dependency_names
    from core.repo_manager import RepoManager
    repo=RepoManager(str(tmp_path),{"requirements.txt","deps/base.txt"},{},git_enabled=False)
    repo.write_file("requirements.txt","-r deps/base.txt\n-c constraints.txt")
    repo.write_file("deps/base.txt","Requests>=2 # install\n")
    assert _manifest_dependency_names(repo)=={"requests"}
    repo.write_file("deps/base.txt","-r ../requirements.txt")
    with pytest.raises(ValueError,match="Circular"):
        _manifest_dependency_names(repo)
