import json
from types import SimpleNamespace

import pytest

from actions.generate_code import GenerateCodeAction
from core.contracts import DeveloperTask, repository_path, to_jsonable
from core.llm import LLMClient
from core.schemas import validate_sds
from utils.sds_parser import parse_sds


def test_nested_class_methods_survive_sds_and_prompt_boundary():
    source = LLMClient(SimpleNamespace(provider="mock"))._mock_sds()
    source["file_specs"][0]["interfaces"]["classes"] = [{
        "name": "Shop", "init_signature": "def __init__(self):",
        "methods": [{"name": "checkout", "signature": "def checkout(self) -> float:"}],
    }]
    spec = to_jsonable(parse_sds(source).file_specs[0])
    prompt = GenerateCodeAction()._build_prompt(spec, {})
    assert "def checkout(self) -> float:" in prompt
    assert json.loads(json.dumps(spec)) == spec


@pytest.mark.parametrize("path", ["../x.py", "/x.py", "C:/x.py", "x/../y.py", ".git/config", "x//y"])
def test_invalid_paths_rejected(path):
    with pytest.raises(ValueError):
        repository_path(path)


def test_duplicate_developer_ids_rejected():
    source = LLMClient(SimpleNamespace(provider="mock"))._mock_sds()
    source["dev_plan"][1]["developer_id"] = "Dev-1"
    with pytest.raises(ValueError, match="unique"):
        validate_sds(source)


def test_task_roundtrip_and_same_file_symbol_reference():
    assert to_jsonable(DeveloperTask("a.py", "fix", {"message": "repair"}))["issues"]["message"] == "repair"
    source = LLMClient(SimpleNamespace(provider="mock"))._mock_sds()
    source["file_specs"][1]["dependencies"] = ["shop/catalog.py::get_price"]
    validate_sds(source)
