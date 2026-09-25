# roles/developer_worker_async.py
from __future__ import annotations
import asyncio
from typing import Dict, List
from actions.generate_code import GenerateCodeAction
from actions.request_briefing import RequestBriefingAction
from utils.logger import get_logger
from core.dependencies import resolve_file_dependencies
from core.call_context import model_call_context
from core.brief_manager import StaleBriefContext

class DeveloperWorkerAsync:
    def __init__(self, agent_id: str, assigned_files: List[str], sds_map: Dict[str, dict],
                 llm, repo_manager, brief_manager, event_bus):
        self.agent_id = agent_id
        self.assigned_files = set(assigned_files)
        self.sds_map = sds_map
        self.dependencies = resolve_file_dependencies(list(sds_map.values()), getattr(repo_manager, "allowed_files_all", None))
        self.llm = llm
        self.repo = repo_manager
        self.briefs = brief_manager
        self.bus = event_bus
        self.log = get_logger(f"dev.{agent_id}")

        self._gen = GenerateCodeAction(llm=llm)
        self._gen.repo_specs = list(sds_map.values())
        self._gen.repo_files = list(getattr(repo_manager, "allowed_files_all", sds_map))
        self._gen.brief_manager = brief_manager
        self._req = RequestBriefingAction()

    async def start(self):
        self.task = asyncio.create_task(self.run(), name=f"Dev-{self.agent_id}")
        return self.task

    async def run(self):
        topic = f"dev_task:{self.agent_id}"
        while True:
            task = await self.bus.take(topic)
            t = task.get("type")
            if t == "exit":
                self.log.info("exit")
                return
            file_path = task["file_path"]
            issues = task.get("issues")
            try:
                file_spec = self.sds_map[file_path]
                for context_attempt in range(3):
                    briefs = await self._collect_briefs(file_spec)
                    try:
                        with model_call_context(role='Developer', agent_id=self.agent_id, file_path=file_path,
                                                stage='repair' if t == 'fix' else 'implementation'):
                            brief = await self._gen.run(file_spec=file_spec, briefs=briefs,
                                                       llm=self.llm, repo_manager=self.repo,
                                                       agent_id=self.agent_id, issues=issues)
                        break
                    except StaleBriefContext:
                        self.briefs.record("stale_context", consumer=file_path, attempt=context_attempt + 1)
                        if context_attempt == 2: raise
                self.briefs.update_brief(file_path, brief, update_reason=brief.get("latest_update_reason"))
                await self.bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path, "update_reason": brief.get("latest_update_reason", {})})
                self.log.info(f"done {t} {file_path}")
            except Exception as e:
                self.log.error(f"error {t} {file_path}: {e}")
                await self.bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path, "error": str(e), "error_type": type(e).__name__})

    async def _collect_briefs(self, file_spec: dict) -> dict:
        briefs = {}
        for dep in sorted(self.dependencies[file_spec["path"]]):
            brief = await self._req.run(target_file=dep, brief_manager=self.briefs)
            if brief is None:
                brief = dict(self.sds_map.get(dep, {}).get("interfaces", {"functions": [], "classes": []}), source="sds_declared")
            briefs[dep] = brief
        return briefs
