import pytest
from core.context_budget import bounded_prompt


def test_context_trims_optional_docs_but_keeps_target_and_records_omissions():
    import json
    build=lambda b,i: "COMPLETE TARGET"+json.dumps(b)+json.dumps(i)
    prompt,receipt=bounded_prompt(build,{"a":{"doc":"x"*3000,"functions":[{"signature":"def f():"}]}},{},200,128)
    assert "COMPLETE TARGET" in prompt and "def f():" in prompt
    assert receipt["actual"]<=200 and receipt["omitted"]


def test_required_context_is_rejected_not_silently_truncated():
    with pytest.raises(ValueError,match="Required developer context") as e:
        bounded_prompt(lambda b,i:"source"*2000,{}, {},100,128)
    assert e.value.receipt["status"].startswith("rejected")
