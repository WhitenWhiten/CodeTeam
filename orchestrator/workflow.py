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
from utils.sds_normalizer import normalize_sds_candidate
from utils.allowed_files import flatten_repo_structure
from utils.event_bus import EventBus
from utils.runtime_dev_plan import build_runtime_sds_json
from runtime_adapters.python_runtime import PythonRuntime
from orchestrator.scheduler import DependencyScheduler
from orchestrator.architect_diversity import build_architect_profiles, update_claimed_summary
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
        profiles = build_architect_profiles(self.ctx.cfg.architects, seed=getattr(self.ctx.cfg, "architect_seed", None))
        sds_list: List[Dict[str, Any]] = []
        traces: List[Dict[str, Any]] = []

        async def one(a, profile, claimed_summary):
            last_err = None
            for _ in range(self.ctx.cfg.sds_retry + 1):
                try:
                    trace = await a.propose_sds(
                        question,
                        design_preference=profile.preference,
                        claimed_summary=claimed_summary,
                        return_trace=True,
                    )
                    sds_json = normalize_sds_candidate(trace["sds"])
                    validate_sds(sds_json)
                    trace["sds"] = sds_json
                    return trace
                except Exception as e:
                    last_err = e
                    continue
            raise last_err or RuntimeError("SDS generation failed")

        for profile in profiles:
            claimed_summary = update_claimed_summary(sds_list)
            arch = ArchitectAgent(name=profile.name, llm=self.ctx.llm, rag=rag_client)
            result = await one(arch, profile, claimed_summary)
            sds_list.append(result["sds"])
            traces.append(
                {
                    "architect": profile.name,
                    "design_preference": profile.preference,
                    "claimed_summary": claimed_summary,
                    "rag_docs": result.get("rag_docs", []),
                    "sds": result["sds"],
                }
            )

        if not sds_list:
            raise RuntimeError("No valid SDS generated")
        self._artifact_json("planning/architect_candidates.json", traces)
        return sds_list

    async def run(self, question: str) -> str:
        self._check_resource_limits()
        self._artifact_text("requirements/normalized_requirements.md", question)
        # 1) Architect
        sds_list = await self._collect_sds(question)
        self._check_resource_limits()
        # 2) CTO select
        cto = CTOAgent(llm=self.ctx.llm, rag=self._rag_client())
        decision = await cto.choose(question, sds_list)
        self._artifact_json("planning/cto_decision.json", decision)
        chosen_sds = build_runtime_sds_json(
            decision["chosen_sds"],
            dynamic_enabled=self.ctx.cfg.developer_allocation.dynamic_enabled,
            fixed_agent_count=self.ctx.cfg.developer_allocation.fixed_agents,
            assignment_seed=self.ctx.cfg.developer_allocation.assignment_seed,
        )
        sds = parse_sds(chosen_sds)  # models.SDS
        self._artifact_json("planning/chosen_sds.json", chosen_sds)
        self._check_resource_limits()

        # 3) Repo init with permissions
        allowed_all: Set[str] = set(flatten_repo_structure(chosen_sds["repo_structure"]))

        # Pre-infer test filenames QA may write, such as tests/test_<stem>.py, and allow them.
        def infer_test_file(path: str) -> str | None:
            p = path.replace("\\", "/")
            if p.startswith("tests/") or not p.endswith(".py"):
                return None
            stem = os.path.splitext(os.path.basename(p))[0]
            return f"tests/test_{stem}.py"

        test_placeholders = {tp for p in allowed_all if (tp := infer_test_file(p))}
        # Add placeholder test files to the global allowlist.
        allowed_all |= test_placeholders

        # Map agents to writable files; QA writes files under tests.
        allowed_by_agent: Dict[str, Set[str]] = {}
        for a in sds.dev_plan:
            allowed_by_agent[a.developer_id] = set(a.file_paths)

        # QA permissions include declared test files and inferred placeholders.
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
        self._artifact_json("repository/repo_root.json", {"repo_root": repo_root})

        # 4) Managers
        brief_mgr = BriefManager()
        event_bus = EventBus()

        # 5) QA init
        qa = QAAgent(self.ctx.llm, repo, PythonRuntime(), event_bus, sds=sds)
        await qa.init_tests(chosen_sds)

        # 6) Dev threads; keep recursive dict conversion for sds_map.
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

        # 7) Initial implementation dispatch: unlock batches by SDS file dependencies.
        scheduler = DependencyScheduler(sds)
        self._run_scheduled_dev_tasks(event_bus, scheduler)
        self._check_resource_limits()

        # 8) Test and fix loop.
        for round_no in range(self.ctx.cfg.max_rounds):
            self._check_resource_limits()
            print(f"Fix Round: {round_no + 1}")
            result = await qa.run_and_feedback()
            self._artifact_json(f"qa/round_{round_no}.json", result)
            if result.get("success", False):
                break
            fixes = result.get("fix_suggestions", [])
            if not fixes:
                break
            fix_payloads = scheduler.requeue_from_fixes(fixes)
            self._run_scheduled_dev_tasks(event_bus, scheduler, payloads=fix_payloads)
            self._check_resource_limits()

        # 9) Stop developer threads.
        for dev in dev_threads:
            event_bus.emit(f"dev_task:{dev.agent_id}", {"type": "exit"})
        finalize_repo = getattr(repo, "finalize_output_repository", None)
        if finalize_repo:
            finalize_repo()
        self._artifact_json("repository/final.json", {"repo_root": str(repo.root)})
        return str(repo.root)

    def _artifact_json(self, path: str, payload: Any) -> None:
        artifacts = getattr(self.ctx, "artifacts", None)
        if artifacts:
            artifacts.write_json(path, payload)

    def _artifact_text(self, path: str, text: str) -> None:
        artifacts = getattr(self.ctx, "artifacts", None)
        if artifacts:
            artifacts.write_text(path, text)

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
