# roles/developer_agent.py
from __future__ import annotations
import threading
from typing import Dict, List
try:
    from metagpt.roles import Role
except ImportError:
    class Role:
        def __init__(self, name: str = ""):
            self.name = name
        def set_actions(self, actions): self._actions = actions
        def run(self, action_cls, **kwargs):
            # 占位，同步转异步简化：直接调用action.run（可能是协程，简化起见假设同步）
            action = None
            for a in self._actions:
                if isinstance(a, action_cls) or (a.__class__ is action_cls):
                    action = a
                    break
            if not action:
                action = action_cls()
            # 这里应是 await，但为了线程 Worker 简化假用同步调用（Mock环境OK）
            coro = action.run(**kwargs)
            if hasattr(coro, "__await__"):
                import asyncio
                return asyncio.get_event_loop().run_until_complete(coro)
            return coro

from actions.generate_code import GenerateCodeAction
from actions.request_briefing import RequestBriefingAction

class DeveloperAgent(Role, threading.Thread):
    def __init__(self, agent_id: str, assigned_files: List[str], sds_map: Dict[str, dict],
                 llm, repo_manager, brief_manager, event_bus):
        Role.__init__(self, name=agent_id)
        threading.Thread.__init__(self, name=agent_id, daemon=True)
        self.agent_id = agent_id
        self.assigned_files = set(assigned_files)
        self.sds_map = sds_map  # path -> file_spec dict
        self.llm = llm
        self.repo = repo_manager
        self.briefs = brief_manager
        self.event_bus = event_bus
        self.set_actions([GenerateCodeAction(llm=llm), RequestBriefingAction()])

    def _collect_briefs(self, file_spec: dict) -> dict:
        briefs = {}
        for dep in file_spec.get("dependencies", []):
            if dep not in self.assigned_files:
                brief = self.run(RequestBriefingAction, target_file=dep, brief_manager=self.briefs)
                if brief:
                    briefs[dep] = brief
        return briefs

    def _implement(self, file_path: str):
        file_spec = self.sds_map[file_path]
        briefs = self._collect_briefs(file_spec)
        brief = self.run(GenerateCodeAction, file_spec=file_spec, briefs=briefs,
                         llm=self.llm, repo_manager=self.repo, agent_id=self.agent_id, issues=None)
        self.briefs.update_brief(file_path, brief)
        self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path})

    def _fix(self, file_path: str, issues: dict):
        file_spec = self.sds_map[file_path]
        briefs = self._collect_briefs(file_spec)
        brief = self.run(GenerateCodeAction, file_spec=file_spec, briefs=briefs,
                         llm=self.llm, repo_manager=self.repo, agent_id=self.agent_id, issues=issues)
        self.briefs.update_brief(file_path, brief)
        self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path})

    def run(self):
        while True:
            task = self.event_bus.take(f"dev_task:{self.agent_id}")
            t = task.get("type")
            if t == "implement":
                self._implement(task["file_path"])
            elif t == "fix":
                self._fix(task["file_path"], task.get("issues", {}))
            elif t == "exit":
                break
