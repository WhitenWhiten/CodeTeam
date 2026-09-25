# roles/qa_agent_async.py
from __future__ import annotations
import ast
from typing import Dict, Any, List, Set
from actions.generate_tests import GenerateTestsAction
from actions.run_tests import RunTestsAction
from core.text_utils import strip_code_fences
from utils.failure_routing import build_fix_suggestions
from utils.logger import get_logger
from core.dependencies import resolve_file_dependencies
from runtime_adapters.runner import command_args

class QAAgentAsync:
    def __init__(self, llm, repo_manager, runtime_adapter, event_bus, sds=None, requirements="", artifacts=None, progressive=True):
        self.llm = llm
        self.repo = repo_manager
        self.adapter = runtime_adapter
        self.bus = event_bus
        self.sds = sds
        self.requirements = requirements
        self.artifacts = artifacts
        self.progressive = progressive
        self.history = []
        self.test_dependencies = {}
        self.fixture_dependencies = {}
        self._snapshot = None
        self._sds_json = None
        self.log = get_logger("QA")
        self.file_owner: Dict[str, str] = {}
        if sds:
            for a in sds.dev_plan:
                for f in a.file_paths:
                    self.file_owner[f] = a.developer_id
        self._gen = GenerateTestsAction(llm=llm)
        self._run = RunTestsAction()
        self.tests: Dict[str, str] = {}
        self.setup_commands: List[str] = []
        self.run_command: str | None = None

    async def init_tests(self, sds_json: dict):
        self._sds_json = sds_json
        await self.refresh_tests(set(), {}, phase="initial")

    def restore(self, bundle, history=None):
        self.tests = dict(bundle["tests"])
        self.run_command = bundle["run_command"]
        self.setup_commands = list(bundle.get("setup_commands", []))
        self.test_dependencies = dict(bundle.get("test_dependencies", {}))
        self.fixture_dependencies = dict(bundle.get("fixture_dependencies", {}))
        self.history = list(history or [])
        self._snapshot = self.history[-1].get("snapshot") if self.history else None

    def bundle(self):
        return {"tests": self.tests, "run_command": self.run_command, "setup_commands": self.setup_commands,
                "test_dependencies": self.test_dependencies, "fixture_dependencies": self.fixture_dependencies}

    async def refresh_tests(self, completed, briefs, phase="batch"):
        import hashlib, json
        if phase != "initial" and not self.progressive: return
        sources = {p: hashlib.sha256(self.repo.read_bytes(p)).hexdigest() for p in sorted(completed) if self.repo.is_file(p)}
        snapshot = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
        if snapshot == self._snapshot: return
        context = {"requirements": self.requirements, "phase": phase, "completed_files": sorted(completed),
                   "source_versions": sources, "interface_briefs": briefs, "existing_tests": self.tests}
        try:
            res = await self._gen.run(sds=self._sds_json, llm=self.llm, context=context)
        finally:
            if self.artifacts:
                self.artifacts.write_json(f"qa/generation_{len(self.history)}.json", {"context": context, "attempts": getattr(self._gen, "attempts", [])})
        added, renamed = [], {}
        version = len(self.history)
        for path, content in res["tests"].items():
            if path in self.tests and self.tests[path] == content: continue
            target = path
            if path in self.tests:
                if path.endswith("conftest.py"):
                    # Existing fixtures are immutable; conflicting proposals remain in the generation trace.
                    continue
                target = path.rsplit("/", 1)[0] + f"/test_round_{version}_" + path.rsplit("/", 1)[1]
                if target in self.tests: raise ValueError(f"QA test identity collision: {target}")
            self.tests[target] = content
            renamed[path] = target
            added.append(target)
        for path, deps in res.get("test_dependencies", {}).items():
            if renamed.get(path, path) in added: self.test_dependencies[renamed.get(path, path)] = deps
        for path, deps in res.get("fixture_dependencies", {}).items():
            if renamed.get(path, path) in added: self.fixture_dependencies[renamed.get(path, path)] = [renamed.get(p, p) for p in deps]
        if self.run_command is None: self.run_command = res["run_command"]
        for command in res.get("setup_commands", []):
            if command not in self.setup_commands: self.setup_commands.append(command)
        self._snapshot = snapshot
        self.history.append({"version": version, "phase": phase, "snapshot": snapshot, "added": added,
                             "test_count": len(self.tests), "source_versions": sources})
        if self.artifacts:
            self.artifacts.write_json("qa/test_history.json", self.history)
            self.artifacts.write_json("qa/test_bundle.json", self.bundle())

    def _ready_tests(self, completed):
        if completed is None or not self.sds:
            return self.tests
        modules = {fs.path[:-3].replace("/", "."): fs.path for fs in self.sds.file_specs if fs.path.endswith(".py")}
        for module, path in list(modules.items()):
            if module.startswith("src."):
                modules[module[4:]] = path
            if module.endswith(".__init__"):
                modules[module[:-9]] = path
        deps = resolve_file_dependencies(self.sds.file_specs, getattr(self.repo, "allowed_files_all", None))
        selected = {}
        for path, code in self.tests.items():
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            referenced = set(self.test_dependencies.get(path, []))
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or "", *[(node.module + "." if node.module else "") + alias.name for alias in node.names]] if isinstance(node, ast.ImportFrom) else [])
                referenced.update(modules[name] for name in names if name in modules)
            queue = list(referenced)
            while queue:
                for dep in deps.get(queue.pop(), set()):
                    if dep not in referenced:
                        referenced.add(dep)
                        queue.append(dep)
            if referenced and referenced.issubset(completed):
                selected[path] = code
        if selected:
            for path, code in self.tests.items():
                if path.endswith("conftest.py"):
                    selected[path] = code
            pending = list(selected)
            while pending:
                for fixture in self.fixture_dependencies.get(pending.pop(), []):
                    if fixture not in selected:
                        selected[fixture] = self.tests[fixture]
                        pending.append(fixture)
        # An explicit target may refer to a test withheld from this batch. Wait
        # until it is ready instead of running pytest against a nonexistent file.
        for argument in command_args(self.run_command or "pytest -q"):
            target = argument.replace("\\", "/").removeprefix("./").split("::", 1)[0]
            if target in self.tests and target not in selected:
                return {}
        return selected

    async def run_and_feedback(self, completed_files=None):
        tests = self._ready_tests(completed_files)
        if not tests:
            return {"success": False, "status": "deferred", "failures": [], "fix_suggestions": []}
        result = await self._run.run(
            repo_root=str(self.repo.root),
            run_command=self.run_command,
            runtime_adapter=self.adapter,
            tests=tests,
            setup_commands=self.setup_commands,
        )
        all_suggestions = self._map_failures(result.get("failures", []))
        fix_suggestions = [fx for fx in all_suggestions if fx.get("requeue", True)]
        result["failure_diagnostics"] = all_suggestions
        result["fix_suggestions"] = fix_suggestions
        emitted = self.bus.emit("qa_result", result)
        import inspect
        if inspect.isawaitable(emitted):
            await emitted
        self.log.info(f"qa_result success={result.get('success')}, fixes={len(fix_suggestions)}")
        return result

    def _map_failures(self, failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return build_fix_suggestions(failures, self.file_owner, sds=self.sds, source_reader=self.repo.read_file)
