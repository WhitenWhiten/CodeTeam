import pytest
from core.brief_manager import BriefManager, StaleBriefContext
from utils.run_artifacts import RunArtifacts


def test_journal_replays_versions_and_consumers(tmp_path):
    artifacts=RunArtifacts(str(tmp_path))
    manager=BriefManager(artifacts)
    manager.update_brief("a.py", {"functions":[],"source_hash":"one","interface_version":"api","commit_sha":"sha"})
    versions=manager.consume("b.py",["a.py"])
    restored=BriefManager(artifacts)
    assert restored.get_brief("a.py")==manager.get_brief("a.py")
    restored.assert_current(versions)
    restored.update_brief("a.py", {"functions":[],"source_hash":"two","interface_version":"api","commit_sha":"next"})
    with pytest.raises(StaleBriefContext): restored.assert_current(versions)
    assert restored.events[1]["kind"]=="consume"
