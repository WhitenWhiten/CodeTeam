import pytest
from app.config import SystemConfig
from core.mechanism_state import MechanismState
from core.contracts import ValidationStopped
from utils.run_artifacts import RunArtifacts


def test_requeue_budget_survives_recovery(tmp_path):
    artifacts=RunArtifacts(str(tmp_path))
    state=MechanismState(artifacts,max_file_requeues=1)
    state.requeue("a.py","interface_change")
    recovered=MechanismState(artifacts, resume=True,max_file_requeues=1)
    with pytest.raises(ValidationStopped): recovered.requeue("a.py","interface_change")
    assert recovered.snapshot()["file_requeues"]=={"a.py":1}


def test_unlimited_qa_needs_global_ceiling():
    with pytest.raises(ValueError, match="global"): SystemConfig(max_rounds=None)
    assert SystemConfig(max_rounds=None,max_model_calls=100).max_rounds is None
