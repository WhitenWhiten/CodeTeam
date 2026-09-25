from actions.generate_code import GenerateCodeAction
from core.ast_utils import to_brief, interface_version
from orchestrator.scheduler import DependencyScheduler


def test_private_helpers_and_docs_do_not_change_public_version():
    a = to_brief("def public():\n    return 1\n")
    b = to_brief('def public():\n    """New docs."""\n    return 2\ndef _helper(): return 3\n')
    assert interface_version(a) == interface_version(b)
    assert GenerateCodeAction()._interface_delta(a,b)[1] == []


def test_constant_attribute_and_reexport_changes_are_versioned():
    for before, after in [("VALUE=1", "VALUE=2"), ("from a import X", "from b import X"),
                          ("class A: value=1", "class A: value=2")]:
        assert interface_version(to_brief(before)) != interface_version(to_brief(after))


def test_internal_fix_does_not_regenerate_consumer():
    s = DependencyScheduler([{"path":"a.py","dependencies":[]},{"path":"b.py","dependencies":["a.py"]}],
                            [{"developer_id":"D", "file_paths":["a.py","b.py"]}])
    s.restore_completed(["a.py","b.py"])
    payloads=s.requeue_from_fixes([{"file_path":"a.py","issues":{"message":"AssertionError"},"affected_dependents":["b.py"],"public_api_changed":False}])
    assert set(payloads)=={"a.py"} and s.completed=={"b.py"}
