# actions/run_tests.py
from __future__ import annotations
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

class RunTestsAction(Action):
    name = "RunTestsAction"
    async def run(self, repo_root, run_command, runtime_adapter):
        return runtime_adapter.run_tests(repo_root, run_command)