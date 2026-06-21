# roles/qa_agent.py
from __future__ import annotations
from typing import Dict, Any, List, Set
try:
    from metagpt.roles import Role
except ImportError:
    class Role:
        def __init__(self, name: str = ""):
            self.name = name
        def set_actions(self, actions): self._actions = actions
        def run(self, action_cls, **kwargs):
            action = None
            for a in self._actions:
                if isinstance(a, action_cls) or (a.__class__ is action_cls):
                    action = a
                    break
            if not action:
                action = action_cls()
            coro = action.run(**kwargs)
            if hasattr(coro, "__await__"):
                import asyncio
                return asyncio.get_event_loop().run_until_complete(coro)
            return coro

from actions.generate_tests import GenerateTestsAction
from actions.run_tests import RunTestsAction
from core.text_utils import strip_code_fences
from utils.failure_routing import build_fix_suggestions

class QAAgent(Role):
    def __init__(self, llm, repo_manager, runtime_adapter, event_bus, sds=None):
        super().__init__(name="QA")
        self.llm = llm
        self.repo = repo_manager
        self.adapter = runtime_adapter
        self.event_bus = event_bus
        self.sds = sds
        self.file_owner: Dict[str, str] = {}
        if sds:
            for a in sds.dev_plan:
                for f in a.file_paths:
                    self.file_owner[f] = a.developer_id
        self._gen = GenerateTestsAction(llm=llm)
        self._run = RunTestsAction()
        self.run_command: str | None = None
        self.tests: Dict[str, str] = {}
        self.setup_commands: List[str] = []

    async def init_tests(self, sds_json: dict):
        res = await self._gen.run(sds=sds_json, llm=self.llm)
        # Keep lightweight QA tests out of the final repo tree; RunTestsAction
        # materializes them under .codeteam_qa/tests for each execution.
        self.tests = {
            fpath: strip_code_fences(content)
            for fpath, content in res["tests"].items()
        }
        self.run_command = res.get("run_command")
        self.setup_commands = list(res.get("setup_commands") or [])

    def _map_failures(self, failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return build_fix_suggestions(failures, self.file_owner, sds=self.sds)

    async def run_and_feedback(self):
        result = await self._run.run(
            repo_root=str(self.repo.root),
            run_command=self.run_command,
            runtime_adapter=self.adapter,
            tests=self.tests,
            setup_commands=self.setup_commands,
        )
        all_suggestions = self._map_failures(result.get("failures", []))
        result["failure_diagnostics"] = all_suggestions
        result["fix_suggestions"] = [fx for fx in all_suggestions if fx.get("requeue", True)]
        self.event_bus.emit("qa_result", result)
        return result
