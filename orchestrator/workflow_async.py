# orchestrator/workflow_async.py
from __future__ import annotations
import asyncio
import time
from typing import Dict, Any, List, Set, Mapping
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
from utils.runtime_dev_plan import build_runtime_sds_json
from runtime_adapters.python_runtime_async import PythonRuntimeAsync
from utils.logger import get_logger, StageTimer
from orchestrator.scheduler import DependencyScheduler

class MultiAgentCodegenWorkflowAsync:
    def __init__(self, ctx):
        self.ctx = ctx
        self.log = get_logger("workflow")
        self._started_at = time.monotonic()

    def _rag_client(self):
        if not getattr(self.ctx.cfg.rag, "enabled", False):
            return None
        return self.ctx.rag

    async def _collect_sds(self, question: str) -> List[Dict[str, Any]]:
        rag_client = self._rag_client()
        archs = [ArchitectAgent(name=f"Architect-{i+1}", llm=self.ctx.llm, rag=rag_client) for i in range(self.ctx.cfg.architects)]
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
        self._check_resource_limits()
        with StageTimer(self.log, "architect_phase"):
            sds_list = await self._collect_sds(question)
        self._check_resource_limits()
        with StageTimer(self.log, "cto_selection"):
            cto = CTOAgent(llm=self.ctx.llm, rag=self._rag_client())
            decision = await cto.choose(question, sds_list)
            chosen_sds = build_runtime_sds_json(
                decision["chosen_sds"],
                dynamic_enabled=self.ctx.cfg.developer_allocation.dynamic_enabled,
                fixed_agent_count=self.ctx.cfg.developer_allocation.fixed_agents,
                assignment_seed=self.ctx.cfg.developer_allocation.assignment_seed,
            )
            sds = parse_sds(chosen_sds)
        self._check_resource_limits()

        allowed_all: Set[str] = set(flatten_repo_structure(chosen_sds["repo_structure"]))
        allowed_by_agent: Dict[str, Set[str]] = {}
        for a in sds.dev_plan:
            allowed_by_agent[a.developer_id] = set(a.file_paths)
        tests_files = {p for p in allowed_all if p.startswith("tests/")}
        allowed_by_agent["QA"] = tests_files

        repo_root = self.ctx.make_repo_root()
        repo = RepoManager(
            repo_root,
            allowed_files_all=allowed_all,
            allowed_files_by_agent=allowed_by_agent,
            git_enabled=self.ctx.cfg.git.enabled,
        )
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

        scheduler = DependencyScheduler(sds)

        # 首轮实现
        with StageTimer(self.log, "dev_round_initial"):
            await self._run_scheduled_dev_tasks(bus, scheduler)
        self._check_resource_limits()

        # 修复迭代
        with StageTimer(self.log, "qa_and_fix_loops"):
            for rnd in range(self.ctx.cfg.max_rounds):
                self._check_resource_limits()
                result = await qa.run_and_feedback()
                if result.get("success", False):
                    self.log.info(f"all tests passed at round {rnd}")
                    break
                fixes = result.get("fix_suggestions", [])
                if not fixes:
                    self.log.warning("no fix suggestions; stopping")
                    break
                fix_payloads = scheduler.requeue_from_fixes(fixes)
                await self._run_scheduled_dev_tasks(bus, scheduler, payloads=fix_payloads)
                self._check_resource_limits()

        # 停止协程
        for a in sds.dev_plan:
            await bus.emit(f"dev_task:{a.developer_id}", {"type":"exit"})
        await asyncio.gather(*dev_tasks, return_exceptions=True)
        finalize_repo = getattr(repo, "finalize_output_repository", None)
        if finalize_repo:
            finalize_repo()
        return str(repo.root)

    def _check_resource_limits(self) -> None:
        max_wall = getattr(self.ctx.cfg, "max_wall_clock_seconds", None)
        if max_wall is not None and time.monotonic() - self._started_at > max_wall:
            raise TimeoutError(f"CodeTeam wall-clock budget exceeded: {max_wall}s")

        max_tokens = getattr(self.ctx.cfg, "max_token_budget", None)
        total_tokens = getattr(self.ctx.llm, "total_tokens", None)
        if max_tokens is not None and isinstance(total_tokens, int) and total_tokens > max_tokens:
            raise RuntimeError(f"CodeTeam token budget exceeded: {total_tokens}>{max_tokens}")

    async def _run_scheduled_dev_tasks(
        self,
        bus: AsyncEventBus,
        scheduler: DependencyScheduler,
        payloads: Mapping[str, Dict[str, Any]] | None = None,
        timeout: float = 600,
    ) -> None:
        payloads = payloads or {}
        while scheduler.has_work():
            self._check_resource_limits()
            for item in scheduler.dispatch_ready():
                payload = dict(payloads.get(item.file_path, {"type": "implement"}))
                payload["file_path"] = item.file_path
                await bus.emit(f"dev_task:{item.owner}", payload)

            scheduler.assert_can_progress()
            try:
                done = await bus.take("dev_done", timeout=timeout)
            except asyncio.TimeoutError as exc:
                running = scheduler.running_files()
                raise TimeoutError(f"Developers round timeout; running={running}") from exc

            file_path = done.get("file") if isinstance(done, dict) else None
            if not file_path:
                raise RuntimeError(f"Malformed dev_done event: {done!r}")
            scheduler.complete(file_path)
            if isinstance(done, dict) and done.get("error"):
                raise RuntimeError(f"Developer failed for {file_path}: {done['error']}")
