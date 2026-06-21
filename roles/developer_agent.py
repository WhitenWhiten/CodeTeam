# roles/developer_agent.py
from __future__ import annotations
import threading
import asyncio
from typing import Dict, List

from actions.generate_code import GenerateCodeAction
from actions.request_briefing import RequestBriefingAction

class DeveloperAgent(threading.Thread):
    def __init__(self, agent_id: str, assigned_files: List[str], sds_map: Dict[str, dict],
                llm, repo_manager, brief_manager, event_bus):
        super().__init__(name=agent_id, daemon=True)  # Correctly initialize Thread.
        self.agent_id = agent_id
        self.assigned_files = set(assigned_files)
        self.sds_map = sds_map # path -> file_spec dict
        self.llm = llm
        self.repo = repo_manager
        self.briefs = brief_manager
        self.event_bus = event_bus
        self._gen = GenerateCodeAction(llm=llm)
        self._req = RequestBriefingAction()
        self._stop_evt = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop and not self._loop.is_closed():
            return self._loop
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        return self._loop

    def _await(self, maybe_coro):
        if hasattr(maybe_coro, "__await__"):
            loop = self._ensure_loop()
            return loop.run_until_complete(maybe_coro)
        return maybe_coro

    def stop(self):
        self._stop_evt.set()

    def _collect_briefs(self, file_spec: dict) -> dict:
        briefs = {}
        extra_count = 0
        for dep in file_spec.get("dependencies", []):
            if dep not in self.assigned_files:
                if extra_count >= 2:
                    break
                extra_count += 1
                res = self._req.run(target_file=dep, brief_manager=self.briefs)
                res = self._await(res)
                if res:
                    briefs[dep] = res
        return briefs

    def _implement(self, file_path: str):
        file_spec = self.sds_map[file_path]
        briefs = self._collect_briefs(file_spec)
        brief = self._await(self._gen.run(
            file_spec=file_spec, briefs=briefs, llm=self.llm,
            repo_manager=self.repo, agent_id=self.agent_id, issues=None
        ))
        self.briefs.update_brief(file_path, brief, update_reason=brief.get("latest_update_reason"))
        self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path})

    def _fix(self, file_path: str, issues: dict):
        file_spec = self.sds_map[file_path]
        briefs = self._collect_briefs(file_spec)
        brief = self._await(self._gen.run(
            file_spec=file_spec, briefs=briefs, llm=self.llm,
            repo_manager=self.repo, agent_id=self.agent_id, issues=issues
        ))
        self.briefs.update_brief(file_path, brief, update_reason=brief.get("latest_update_reason"))
        self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path})

    def run(self):
        topic = f"dev_task:{self.agent_id}"
        while not self._stop_evt.is_set():
            task = self.event_bus.take(topic)
            if not task:
                continue
            t = task.get("type")
            if t == "implement":
                self._implement(task["file_path"])
            elif t == "fix":
                self._fix(task["file_path"], task.get("issues", {}))
            elif t == "exit":
                break
