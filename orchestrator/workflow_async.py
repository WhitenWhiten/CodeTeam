# orchestrator/workflow_async.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Set
from roles.architect_agent import ArchitectAgent
from roles.cto_agent import CTOAgent
from roles.developer_worker_async import DeveloperWorkerAsync
from roles.qa_agent_async import QAAgentAsync
from core.repo_manager import RepoManager
from core.brief_manager import BriefManager
from core.schemas import validate_sds
from utils.sds_parser import parse_sds
from utils.allowed_files import flatten_repo_structure
from utils.event_bus_async import AsyncEventBus
from runtime_adapters.python_runtime_async import PythonRuntimeAsync
from utils.logger import get_logger, StageTimer

class MultiAgentCodegenWorkflowAsync:
    def __init__(self, ctx):
        self.ctx = ctx
        self.log = get_logger("workflow")

    async def _collect_sds(self, question: str) -> List[Dict[str, Any]]:
        archs = [ArchitectAgent(name=f"Architect-{i+1}", llm=self.ctx.llm, rag=self.ctx.rag) for i in range(self.ctx.cfg.architects)]
        async def one(a):
            for _ in range(self.ctx.cfg.sds_retry + 1):
                try:
                    sds_json = await a.propose_sds(question)
                    validate_sds(sds_json)
                    return sds_json
                except Exception:
                    continue
            raise RuntimeError("SDS generation failed")
        results = await asyncio.gather(*[one(a) for a in archs], return_exceptions=True)
        sds_list = [r for r in results if not isinstance(r, Exception)]
        if not sds_list:
            raise RuntimeError("No valid SDS generated")
        self.log.info(f"SDS collected: {len(sds_list)}")
        return sds_list

    async def run(self, question: str) -> str:
        with StageTimer(self.log, "architect_phase"):
            sds_list = await self._collect_sds(question)
        with StageTimer(self.log, "cto_selection"):
            cto = CTOAgent(llm=self.ctx.llm, rag=self.ctx.rag)
            decision = await cto.choose(question, sds_list)
            chosen_sds = decision["chosen_sds"]
            sds = parse_sds(chosen_sds)

        allowed_all: Set[str] = set(flatten_repo_structure(chosen_sds["repo_structure"]))
        allowed_by_agent: Dict[str, Set[str]] = {}
        for a in sds.dev_plan:
            allowed_by_agent[a.developer_id] = set(a.file_paths)
        tests_files = {p for p in allowed_all if p.startswith("tests/")}
        allowed_by_agent["QA"] = tests_files

        repo_root = self.ctx.make_repo_root()
        repo = RepoManager(repo_root, allowed_files_all=allowed_all, allowed_files_by_agent=allowed_by_agent)
        repo.init_structure(sds.repo_structure)
        brief_mgr = BriefManager()
        bus = AsyncEventBus()

        qa = QAAgentAsync(self.ctx.llm, repo, PythonRuntimeAsync(), bus, sds=sds)
        with StageTimer(self.log, "qa_init_tests"):
            await qa.init_tests(chosen_sds)

        sds_map: Dict[str, dict] = {fs.path: {
            "path": fs.path,
            "responsibilities": fs.responsibilities,
            "interfaces": {
                "functions": [f.__dict__ for f in fs.interfaces["functions"]],
                "classes": [c.__dict__ for c in fs.interfaces["classes"]],
            },
            "dependencies": fs.dependencies
        } for fs in sds.file_specs}

        dev_tasks = []
        for a in sds.dev_plan:
            worker = DeveloperWorkerAsync(a.developer_id, a.file_paths, sds_map, self.ctx.llm, repo, brief_mgr, bus)
            dev_tasks.append(await worker.start())

        # 首轮实现
        with StageTimer(self.log, "dev_round_initial"):
            for fs in sds.file_specs:
                dev_id = next(d.developer_id for d in sds.dev_plan if fs.path in d.file_paths)
                await bus.emit(f"dev_task:{dev_id}", {"type":"implement", "file_path": fs.path})
            ok = await bus.wait_for_count("dev_done", expected=len(sds.file_specs), timeout=600)
            if not ok: raise TimeoutError("Developers initial round timeout")

        # 修复迭代
        with StageTimer(self.log, "qa_and_fix_loops"):
            for rnd in range(self.ctx.cfg.max_rounds):
                result = await qa.run_and_feedback()
                if result.get("success", False):
                    self.log.info(f"all tests passed at round {rnd}")
                    break
                fixes = result.get("fix_suggestions", [])
                if not fixes:
                    self.log.warning("no fix suggestions; stopping")
                    break
                for fx in fixes:
                    await bus.emit(f"dev_task:{fx['dev_id']}", {"type":"fix", "file_path": fx["file_path"], "issues": fx.get("issues", {})})
                ok = await bus.wait_for_count("dev_done", expected=len(fixes), timeout=600)
                if not ok:
                    raise TimeoutError("Developers fix round timeout")

        # 停止协程
        for a in sds.dev_plan:
            await bus.emit(f"dev_task:{a.developer_id}", {"type":"exit"})
        await asyncio.gather(*dev_tasks, return_exceptions=True)
        return str(repo.root)