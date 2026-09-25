# orchestrator/workflow_async.py
from __future__ import annotations
import asyncio
import time
import hashlib
import json
from typing import Dict, Any, List, Set, Mapping
from roles.architect_agent import ArchitectAgent
from roles.cto_agent import CTOAgent
from roles.developer_worker_async import DeveloperWorkerAsync
from roles.qa_agent_async import QAAgentAsync
from core.repo_manager import RepoManager
from core.brief_manager import BriefManager
from core.schemas import validate_sds
from core.contracts import BudgetExceeded, RunResult, RunStatus, ValidationStopped, to_jsonable
from utils.sds_parser import parse_sds
from utils.sds_normalizer import normalize_sds_candidate
from utils.allowed_files import flatten_repo_structure
from utils.event_bus_async import AsyncEventBus
from utils.runtime_dev_plan import build_runtime_sds_json
from runtime_adapters.python_runtime_async import PythonRuntimeAsync
from utils.logger import get_logger, StageTimer
from orchestrator.scheduler import DependencyScheduler
from orchestrator.architect_diversity import build_architect_profiles, update_claimed_summary

class MultiAgentCodegenWorkflowAsync:
    def __init__(self, ctx):
        self.ctx = ctx
        self.log = get_logger("workflow")
        self._started_at = time.monotonic()
        self._running = False
        self._dev_tasks = []
        self.result = None
        self._repo = None
        self._verification_count = 0
        self._failed_states = set()

    def _set_stage(self, stage):
        self.result.stage = stage

    async def run(self, question: str) -> RunResult:
        if self._running:
            raise RuntimeError("A workflow instance cannot run concurrently")
        self._running = True
        self._started_at = time.monotonic()
        self._dev_tasks = []
        self._repo = None
        self._verification_count = 0
        self._failed_states = set()
        artifacts = getattr(self.ctx, "artifacts", None)
        self.result = RunResult(RunStatus.ERROR, artifacts_dir=str(artifacts.root) if artifacts and artifacts.root else None)
        try:
            limit = getattr(self.ctx.cfg, "max_wall_clock_seconds", None)
            async with asyncio.timeout(limit):
                await self._execute(question)
            self.result.status = (RunStatus.SUCCESS if self.result.qa and self.result.qa.get("success")
                                  else RunStatus.VALIDATION_FAILED)
            if not self.result.success and not self.result.reason:
                self.result.reason = "Repository has not passed final validation"
        except BudgetExceeded as exc:
            self.result.status = RunStatus.BUDGET_EXHAUSTED
            self.result.reason = str(exc)
        except ValidationStopped as exc:
            self.result.status = RunStatus.VALIDATION_FAILED
            self.result.reason = str(exc)
        except TimeoutError as exc:
            self.result.status = RunStatus.BUDGET_EXHAUSTED
            self.result.reason = str(exc) or "Workflow wall-clock limit exceeded"
        except asyncio.CancelledError:
            self.result.status = RunStatus.CANCELLED
            self.result.reason = "Run cancelled"
            raise
        except Exception as exc:
            self.result.status = RunStatus.ERROR
            self.result.reason = f"{type(exc).__name__}: {exc}"
            self.log.exception("workflow failed")
        finally:
            for task in self._dev_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._dev_tasks, return_exceptions=True)
            if self._repo is not None:
                self._repo.cleanup_runtime_artifacts()
            self._running = False
            self._artifact_json("repository/final.json", to_jsonable(self.result))
        return self.result

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
                except Exception:
                    continue
            raise RuntimeError("SDS generation failed")

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
        self.log.info(f"SDS collected: {len(sds_list)}")
        return sds_list

    async def _execute(self, question: str) -> str:
        self._check_resource_limits()
        self._artifact_text("requirements/normalized_requirements.md", question)
        self._set_stage("planning")
        with StageTimer(self.log, "architect_phase"):
            sds_list = await self._collect_sds(question)
        self._check_resource_limits()
        self._set_stage("selection")
        with StageTimer(self.log, "cto_selection"):
            cto = CTOAgent(llm=self.ctx.llm, rag=self._rag_client())
            decision = await cto.choose(question, sds_list)
            self._artifact_json("planning/cto_decision.json", decision)
            chosen_sds = build_runtime_sds_json(
                decision["chosen_sds"],
                dynamic_enabled=self.ctx.cfg.developer_allocation.dynamic_enabled,
                fixed_agent_count=self.ctx.cfg.developer_allocation.fixed_agents,
                assignment_seed=self.ctx.cfg.developer_allocation.assignment_seed,
            )
            sds = parse_sds(chosen_sds)
            self._artifact_json("planning/chosen_sds.json", chosen_sds)
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
        self._repo = repo
        self.result.repo_root = repo_root
        self._set_stage("initialization")
        self._artifact_json("repository/repo_root.json", {"repo_root": repo_root})
        brief_mgr = BriefManager()
        bus = AsyncEventBus()

        qa = QAAgentAsync(self.ctx.llm, repo, PythonRuntimeAsync(), bus, sds=sds)
        with StageTimer(self.log, "qa_init_tests"):
            await qa.init_tests(chosen_sds)

        sds_map: Dict[str, dict] = {fs.path: to_jsonable(fs) for fs in sds.file_specs}

        dev_tasks = self._dev_tasks
        for a in sds.dev_plan:
            worker = DeveloperWorkerAsync(a.developer_id, a.file_paths, sds_map, self.ctx.llm, repo, brief_mgr, bus)
            dev_tasks.append(await worker.start())

        scheduler = DependencyScheduler(sds)

        # Initial implementation round.
        self._set_stage("implementation")
        with StageTimer(self.log, "dev_round_initial"):
            await self._run_scheduled_dev_tasks(bus, scheduler, qa=qa)
        self._check_resource_limits()

        # Every final mutation is followed by a full test run. max_rounds bounds repairs.
        with StageTimer(self.log, "qa_and_fix_loops"):
            while True:
                fixes = await self._verify(qa, scheduler)
                if not fixes:
                    break
                fix_payloads = scheduler.requeue_from_fixes(fixes)
                self._set_stage("repair")
                self.result.qa = None
                await self._run_scheduled_dev_tasks(bus, scheduler, payloads=fix_payloads)
                self._check_resource_limits()

        # Stop worker coroutines.
        for a in sds.dev_plan:
            await bus.emit(f"dev_task:{a.developer_id}", {"type":"exit"})
        await asyncio.gather(*dev_tasks, return_exceptions=True)
        finalize_repo = getattr(repo, "finalize_output_repository", None)
        if finalize_repo:
            finalize_repo()
        self._set_stage("finished")
        return str(repo.root)

    async def _verify(self, qa, scheduler, partial=False):
        self._check_resource_limits()
        self._set_stage("validation")
        result = await qa.run_and_feedback(completed_files=scheduler.completed if partial else None)
        result["scope"] = "batch" if partial else "full"
        self._artifact_json(f"qa/round_{self._verification_count}.json", result)
        self._verification_count += 1
        if result.get("status") == "deferred" and partial:
            return []
        self.result.qa = result
        if result.get("success"):
            return []
        failures = [{k: f.get(k) for k in ("nodeid", "file_path", "category", "message")} for f in result.get("failures", [])]
        digest = hashlib.sha256(json.dumps(failures, sort_keys=True).encode())
        for path in scheduler.files:
            digest.update(self._repo.read_bytes(path))
        fingerprint = digest.hexdigest()
        if fingerprint in self._failed_states:
            raise ValidationStopped("Repair made no progress: unchanged sources and repeated failures")
        self._failed_states.add(fingerprint)
        if self.result.repairs >= self.ctx.cfg.max_rounds:
            raise ValidationStopped("Repair limit reached; final validation still fails")
        fixes = result.get("fix_suggestions", [])
        if not fixes:
            raise ValidationStopped(f"No actionable source repair for {result.get('status', 'test failure')}")
        self.result.repairs += 1
        return fixes

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
            raise BudgetExceeded(f"CodeTeam wall-clock budget exceeded: {max_wall}s")

        max_tokens = getattr(self.ctx.cfg, "max_token_budget", None)
        total_tokens = getattr(self.ctx.llm, "total_tokens", None)
        if max_tokens is not None and isinstance(total_tokens, int) and total_tokens > max_tokens:
            raise BudgetExceeded(f"CodeTeam token budget exceeded: {total_tokens}>{max_tokens}")

    async def _run_scheduled_dev_tasks(
        self,
        bus: AsyncEventBus,
        scheduler: DependencyScheduler,
        payloads: Mapping[str, Dict[str, Any]] | None = None,
        timeout: float = 600,
        qa=None,
    ) -> None:
        payloads = dict(payloads or {})
        while scheduler.has_work():
            self._check_resource_limits()
            batch = scheduler.dispatch_ready()
            for item in batch:
                payload = dict(payloads.get(item.file_path, {"type": "implement"}))
                payload["file_path"] = item.file_path
                await bus.emit(f"dev_task:{item.owner}", payload)

            scheduler.assert_can_progress()
            changed = []
            for _ in batch:
                try:
                    done = await bus.take("dev_done", timeout=timeout)
                except asyncio.TimeoutError as exc:
                    raise RuntimeError(f"Developers timed out; running={scheduler.running_files()}") from exc
                file_path = done.get("file") if isinstance(done, dict) else None
                if not file_path or done.get("error"):
                    raise RuntimeError(f"Developer failed: {done!r}")
                scheduler.complete(file_path)
                if done.get("update_reason", {}).get("public_api_changed"):
                    changed.append(file_path)
            for path in changed:
                stale = set(scheduler.transitive_dependents(path)) & scheduler.completed
                scheduler.requeue_files(stale)
                for dependent in stale:
                    payloads[dependent] = {"type": "fix", "issues": {"upstream_file": path, "reason": "Upstream interface changed"}}
            if qa is not None:
                fixes = await self._verify(qa, scheduler, partial=True)
                if fixes:
                    payloads.update(scheduler.requeue_from_fixes(fixes))
                    self.result.qa = None
            self._set_stage("implementation")
