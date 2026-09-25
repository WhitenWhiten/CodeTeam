import json
from types import SimpleNamespace
from rag.information import information_record, make_packet, render_documents
from rag.rag_client import RAGClient
from actions.generate_sds import GenerateSDSAction
from actions.select_sds import SelectSDSAction


def test_raw_readme_and_missing_interfaces_are_distinct():
    info=information_record({"readme":"Raw README"})
    assert info["readme"]["representation"]=="raw"
    assert not info["interfaces"]["available"]


def test_packet_replay_matches_both_prompt_boundaries_without_corpus(tmp_path):
    packet=make_packet("task",[{"text":"x"*1000,"meta":{"source":"repo"}}],5,256)
    assert len(packet["injected_text"])==256 and packet["truncation"]
    path=tmp_path/"packet.json"; path.write_text(json.dumps(packet))
    client=RAGClient(SimpleNamespace(frozen_packet_file=str(path),max_injected_chars=256))
    docs=client.query("task")
    assert client.status["active_backend"]=="frozen_packet"
    assert GenerateSDSAction()._render_rag(docs)==SelectSDSAction()._render_rag(docs)==packet["injected_text"]
