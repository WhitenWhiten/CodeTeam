# roles/developer_worker_async.py
from __future__ import annotations
import asyncio
from typing import Dict, List
from actions.generate_code import GenerateCodeAction
from actions.request_briefing import RequestBriefingAction
from utils.logger import get_logger

class DeveloperWorkerAsync:
    def __init__(self, agent_id: str, assigned_files: List[str], sds_map: Dict[str, dict],
                 llm, repo_manager, brief_manager, event_bus):
        self.agent_id = agent_id
        self.assigned_files = set(assigned_files)
        self.sds_map = sds_map
        self.llm = llm
        self.repo = repo_manager
        self.briefs = brief_manager
        self.bus = event_bus
        self.log = get_logger(f"dev.{agent_id}")

        self._gen = GenerateCodeAction(llm=llm)
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
                briefs = await self._collect_briefs(file_spec)
                brief = await self._gen.run(file_spec=file_spec, briefs=briefs,
                                            llm=self.llm, repo_manager=self.repo,
                                            agent_id=self.agent_id, issues=issues)
                self.briefs.update_brief(file_path, brief)
                await self.bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path})
                self.log.info(f"done {t} {file_path}")
            except Exception as e:
                self.log.error(f"error {t} {file_path}: {e}")
                await self.bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_path, "error": str(e)})

    async def _collect_briefs(self, file_spec: dict) -> dict:
        briefs = {}
        for dep in file_spec.get("dependencies", []):
            if dep not in self.assigned_files:
                # 同步动作，直接调用
                brief = await self._req.run(target_file=dep, brief_manager=self.briefs)
                if brief:
                    briefs[dep] = brief
        return briefs
