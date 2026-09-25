"""Durable mechanism counters, independent of model token/call accounting."""
from copy import deepcopy
from core.contracts import ValidationStopped


class MechanismState:
    def __init__(self, artifacts=None, resume=False, max_file_requeues=8):
        self.artifacts=artifacts
        self.max_file_requeues=max_file_requeues
        self.data={"counters":{},"file_requeues":{}}
        if resume and artifacts and artifacts.root and (artifacts.root/"mechanism_state.json").exists():
            self.data=artifacts.read_json("mechanism_state.json")

    def bump(self, name, **details):
        counters=self.data["counters"]
        counters[name]=counters.get(name,0)+1
        if self.artifacts:
            self.artifacts.write_json("mechanism_state.json",self.data)
            self.artifacts.event("mechanism_action",action=name,number=counters[name],**details)

    def requeue(self,path,reason):
        used=self.data["file_requeues"].get(path,0)
        if used>=self.max_file_requeues:
            self.bump("requeue_limit",file_path=path,reason=reason)
            raise ValidationStopped(f"File requeue limit reached: {path} ({used})")
        self.data["file_requeues"][path]=used+1
        self.bump("file_requeues",file_path=path,reason=reason)

    def snapshot(self):
        return deepcopy(self.data)


def count(llm,name,**details):
    state=getattr(llm,"mechanism_state",None)
    if state: state.bump(name,**details)
