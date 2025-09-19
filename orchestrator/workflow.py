# orchestrator/workflow.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Set
from roles.architect_agent import ArchitectAgent
from roles.cto_agent import CTOAgent
from roles.developer_agent import DeveloperAgent
from roles.qa_agent import QAAgent
from core.repo_manager import RepoManager
from core.brief_manager import BriefManager
from core.schemas import validate_sds
from core import models
from utils.sds_parser import parse_sds
from utils.allowed_files import flatten_repo_structure
from utils.event_bus import EventBus
from runtime_adapters.python_runtime import PythonRuntime

class MultiAgentCodegenWorkflow:
    def __init__(self, ctx):
        self.ctx = ctx

    async def _collect_sds(self, question: str) -> List[Dict[str, Any]]:
        archs = [ArchitectAgent(name=f"Architect-{i+1}", llm=self.ctx.llm, rag=self.ctx.rag) for i in range(self.ctx.cfg.architects)]
        async def one(a):
            last_err = None
            for _ in range(self.ctx.cfg.sds_retry + 1):
                try:
                    sds_json = await a.propose_sds(question)
                    validate_sds(sds_json)
                    return sds_json
                except Exception as e:
                    last_err = e
                    continue
            raise last_err or RuntimeError("SDS generation failed")
        results = await asyncio.gather(*[one(a) for a in archs], return_exceptions=True)
        sds_list = [r for r in results if not isinstance(r, Exception)]
        if not sds_list:
            raise RuntimeError("No valid SDS generated")
        return sds_list

    async def run(self, question: str) -> str:
        # 1) Architect
        sds_list = await self._collect_sds(question)
        # 2) CTO select
        cto = CTOAgent(llm=self.ctx.llm, rag=self.ctx.rag)
        decision = await cto.choose(question, sds_list)
        chosen_sds = decision["chosen_sds"]
        sds = parse_sds(chosen_sds)  # models.SDS
        # 3) Repo init with permissions
        allowed_all: Set[str] = set(flatten_repo_structure(chosen_sds["repo_structure"]))
        # map: agent->files；QA写 tests 下文件
        allowed_by_agent: Dict[str, Set[str]] = {}
        for a in sds.dev_plan:
            allowed_by_agent[a.developer_id] = set(a.file_paths)
        # QA 权限：repo_structure 中 tests 下的文件
        tests_files = {p for p in allowed_all if p.startswith("tests/")}
        allowed_by_agent["QA"] = tests_files
        repo_root = self.ctx.make_repo_root()
        repo = RepoManager(repo_root, allowed_files_all=allowed_all, allowed_files_by_agent=allowed_by_agent)
        repo.init_structure(sds.repo_structure)
        # 4) Managers
        brief_mgr = BriefManager()
        event_bus = EventBus()
        # 5) QA init
        qa = QAAgent(self.ctx.llm, repo, PythonRuntime(), event_bus, sds=sds)
        await qa.init_tests(chosen_sds)
        # 6) Dev threads
        sds_map: Dict[str, dict] = {fs.path: {
            "path": fs.path,
            "responsibilities": fs.responsibilities,
            "interfaces": {
                "functions": [f.__dict__ for f in fs.interfaces["functions"]],
                "classes": [c.__dict__ for c in fs.interfaces["classes"]],
            },
            "dependencies": fs.dependencies
        } for fs in sds.file_specs}
        dev_threads: List[DeveloperAgent] = []
        for a in sds.dev_plan:
            dev = DeveloperAgent(a.developer_id, a.file_paths, sds_map, self.ctx.llm, repo, brief_mgr, event_bus)
            dev.start()
            dev_threads.append(dev)
        # 7) 首轮实现任务分发
        for fs in sds.file_specs:
            dev_id = next(d.developer_id for d in sds.dev_plan if fs.path in d.file_paths)
            event_bus.emit(f"dev_task:{dev_id}", {"type": "implement", "file_path": fs.path})
        # 等待首轮完成
        self._await_dev_round_done(event_bus, expected=len(sds.file_specs))
        # 8) 测试与修复循环
        for round_no in range(self.ctx.cfg.max_rounds):
            result = await qa.run_and_feedback()
            if result.get("success", False):
                break
            fixes = result.get("fix_suggestions", [])
            if not fixes:
                # 没有定位到具体文件，保守结束以避免死循环
                break
            # 分发修复任务
            for fx in fixes:
                event_bus.emit(f"dev_task:{fx['dev_id']}", {"type": "fix", "file_path": fx["file_path"], "issues": fx.get("issues", {})})
            # 等待修复数量完成
            self._await_dev_round_done(event_bus, expected=len(fixes))
        # 9) 停止开发者线程
        for dev in dev_threads:
            event_bus.emit(f"dev_task:{dev.agent_id}", {"type": "exit"})
        return str(repo.root)

    def _await_dev_round_done(self, event_bus, expected: int):
        ok = event_bus.wait_for_count("dev_done", expected=expected, timeout=600)
        if not ok:
            raise TimeoutError("Developers round timeout")
