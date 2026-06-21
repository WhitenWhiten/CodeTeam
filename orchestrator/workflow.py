# orchestrator/workflow.py
from __future__ import annotations
import asyncio
import time
from queue import Empty
from typing import Dict, Any, List, Set, Mapping
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
from utils.runtime_dev_plan import build_runtime_sds_json
from runtime_adapters.python_runtime import PythonRuntime
from orchestrator.scheduler import DependencyScheduler
import os

class MultiAgentCodegenWorkflow:
    def __init__(self, ctx):
        self.ctx = ctx
        self._started_at = time.monotonic()

    def _rag_client(self):
        if not getattr(self.ctx.cfg.rag, "enabled", False):
            return None
        return self.ctx.rag

    async def _collect_sds(self, question: str) -> List[Dict[str, Any]]:
        rag_client = self._rag_client()
        archs = [ArchitectAgent(name=f"Architect-{i+1}", llm=self.ctx.llm, rag=rag_client) for i in range(self.ctx.cfg.architects)]
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
        self._check_resource_limits()
        # 1) Architect
        sds_list = await self._collect_sds(question)
        self._check_resource_limits()
        # 2) CTO select
        cto = CTOAgent(llm=self.ctx.llm, rag=self._rag_client())
        decision = await cto.choose(question, sds_list)
        chosen_sds = build_runtime_sds_json(
            decision["chosen_sds"],
            dynamic_enabled=self.ctx.cfg.developer_allocation.dynamic_enabled,
            fixed_agent_count=self.ctx.cfg.developer_allocation.fixed_agents,
            assignment_seed=self.ctx.cfg.developer_allocation.assignment_seed,
        )
        sds = parse_sds(chosen_sds)  # models.SDS
        self._check_resource_limits()

        # 3) Repo init with permissions
        allowed_all: Set[str] = set(flatten_repo_structure(chosen_sds["repo_structure"]))

        # 预推断 QA 将要写入的测试文件名（如 tests/test_<stem>.py），加入权限集合
        def infer_test_file(path: str) -> str | None:
            p = path.replace("\\", "/")
            if p.startswith("tests/") or not p.endswith(".py"):
                return None
            stem = os.path.splitext(os.path.basename(p))[0]
            return f"tests/test_{stem}.py"

        test_placeholders = {tp for p in allowed_all if (tp := infer_test_file(p))}
        # 将占位测试文件加入全局允许集合
        allowed_all |= test_placeholders

        # map: agent->files；QA写 tests 下文件
        allowed_by_agent: Dict[str, Set[str]] = {}
        for a in sds.dev_plan:
            allowed_by_agent[a.developer_id] = set(a.file_paths)

        # QA 权限：加入所有已声明的 tests/ 下文件，以及占位测试文件
        tests_files = {p for p in allowed_all if p.startswith("tests/")}
        allowed_by_agent["QA"] = tests_files | test_placeholders

        repo_root = self.ctx.make_repo_root()
        repo = RepoManager(
            repo_root,
            allowed_files_all=allowed_all,
            allowed_files_by_agent=allowed_by_agent,
            git_enabled=self.ctx.cfg.git.enabled,
        )
        repo.init_structure(sds.repo_structure)

        # 4) Managers
        brief_mgr = BriefManager()
        event_bus = EventBus()

        # 5) QA init
        qa = QAAgent(self.ctx.llm, repo, PythonRuntime(), event_bus, sds=sds)
        await qa.init_tests(chosen_sds)

        # 6) Dev threads（保持对 sds_map 的递归字典化修复）
        sds_map: Dict[str, dict] = {}
        for fs in sds.file_specs:
            func_dicts = [getattr(f, "__dict__", f) for f in fs.interfaces["functions"]]
            class_dicts = []
            for c in fs.interfaces["classes"]:
                c_dict = getattr(c, "__dict__", c)
                methods = c_dict.get("methods", []) if isinstance(c_dict, dict) else getattr(c, "methods", [])
                methods_dicts = [getattr(m, "__dict__", m) for m in methods]
                c_copy = dict(c_dict) if isinstance(c_dict, dict) else dict(c.__dict__)
                c_copy["methods"] = methods_dicts
                class_dicts.append(c_copy)

            sds_map[fs.path] = {
                "path": fs.path,
                "responsibilities": fs.responsibilities,
                "interfaces": {
                    "functions": func_dicts,
                    "classes": class_dicts,
                },
                "dependencies": fs.dependencies
            }

        dev_threads = []
        for a in sds.dev_plan:
            dev = DeveloperAgent(a.developer_id, a.file_paths, sds_map, self.ctx.llm, repo, brief_mgr, event_bus)
            dev.start()
            dev_threads.append(dev)

        # 7) 首轮实现任务分发：按 SDS 文件依赖逐批解锁
        scheduler = DependencyScheduler(sds)
        self._run_scheduled_dev_tasks(event_bus, scheduler)
        self._check_resource_limits()

        # 8) 测试与修复循环
        for round_no in range(self.ctx.cfg.max_rounds):
            self._check_resource_limits()
            print(f"Fix Round: {round_no + 1}")
            result = await qa.run_and_feedback()
            if result.get("success", False):
                break
            fixes = result.get("fix_suggestions", [])
            if not fixes:
                break
            fix_payloads = scheduler.requeue_from_fixes(fixes)
            self._run_scheduled_dev_tasks(event_bus, scheduler, payloads=fix_payloads)
            self._check_resource_limits()

        # 9) 停止开发者线程
        for dev in dev_threads:
            event_bus.emit(f"dev_task:{dev.agent_id}", {"type": "exit"})
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

    def _await_dev_round_done(self, event_bus, expected: int):
        ok = event_bus.wait_for_count("dev_done", expected=expected, timeout=600)
        if not ok:
            raise TimeoutError("Developers round timeout")

    def _run_scheduled_dev_tasks(
        self,
        event_bus: EventBus,
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
                event_bus.emit(f"dev_task:{item.owner}", payload)

            scheduler.assert_can_progress()
            try:
                done = event_bus.take("dev_done", timeout=timeout)
            except Empty as exc:
                running = scheduler.running_files()
                raise TimeoutError(f"Developers round timeout; running={running}") from exc

            file_path = done.get("file") if isinstance(done, dict) else None
            if not file_path:
                raise RuntimeError(f"Malformed dev_done event: {done!r}")
            scheduler.complete(file_path)
            if isinstance(done, dict) and done.get("error"):
                raise RuntimeError(f"Developer failed for {file_path}: {done['error']}")
