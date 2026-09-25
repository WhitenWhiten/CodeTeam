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
    def __init__(self, llm, repo_manager, runtime_adapter, event_bus, sds=None):
        self.llm = llm
        self.repo = repo_manager
        self.adapter = runtime_adapter
        self.bus = event_bus
        self.sds = sds
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
        res = await self._gen.run(sds=sds_json, llm=self.llm)
        self.tests = {
            fpath: strip_code_fences(content)
            for fpath, content in res["tests"].items()
        }
        self.run_command = res["run_command"]
        self.setup_commands = list(res.get("setup_commands") or [])
        self.log.info("tests initialized")

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
            referenced = set()
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
        return build_fix_suggestions(failures, self.file_owner, sds=self.sds)
