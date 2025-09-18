# orchestrator/workflow.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
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

    async def _collect_sds(self, question):
        archs = [ArchitectAgent(name=f"Architect-{i+1}", llm=self.ctx.llm, rag=self.ctx.rag) for i in range(self.ctx.cfg.architects)]
        sds_list = []
        for a in archs:
            for _ in range(self.ctx.cfg.sds_retry + 1):
                try:
                    sds_json = await a.propose_sds(question)
                    validate_sds(sds_json)
                    sds_list.append(sds_json)
                    break
                except Exception as e:
                    continue
        return sds_list

    async def run(self, question: str):
        # 1) Architect 并发
        sds_list = await self._collect_sds(question)
        # 2) CTO 选择
        cto = CTOAgent(llm=self.ctx.llm, rag=self.ctx.rag)
        decision = await cto.choose(question, sds_list)
        chosen_sds = decision["chosen_sds"]
        # 3) 解析 SDS
        sds = parse_sds(chosen_sds)  # -> models.SDS
        allowed_files = set(flatten_repo_structure(sds.repo_structure))
        # 4) 初始化 Repo
        repo_root = self.ctx.make_repo_root()
        repo = RepoManager(repo_root, allowed_files)
        repo.init_structure(sds.repo_structure)
        # 5) Brief Manager & Event Bus
        brief_mgr = BriefManager()
        event_bus = EventBus()
        # 6) QA 初始化
        adapter = PythonRuntime()  # 简化：初版只支持 Python
        # 片段：初始化 QA 时传入 sds，且allowed_files从 chosen_sds解析
        qa = QAAgent(self.ctx.llm, repo, adapter, event_bus, sds=sds)
        await qa.init_tests(chosen_sds)
        # 7) Developer 线程
        dev_threads = []
        assignment = {d.developer_id: d.file_paths for d in sds.dev_plan}
        for dev_id, files in assignment.items():
            dev = DeveloperAgent(dev_id, files, self.ctx.llm, repo, brief_mgr, event_bus)
            dev.start()
            dev_threads.append(dev)
        # 8) 第一轮实现任务分发
        for fs in sds.file_specs:
            dev_id = next(d.developer_id for d in sds.dev_plan if fs.path in d.file_paths)
            event_bus.emit(f"dev_task:{dev_id}", {"type":"implement", "file_spec": fs.__dict__})
        # 9) 迭代回合
        for round_no in range(self.ctx.cfg.max_rounds):
            # 等待所有 dev 完成本轮（可通过计数器/事件来实现）
            self._await_dev_round_done(event_bus, expected=len(sds.file_specs))
            result = await qa.run_and_feedback()
            if result["success"]:
                break
            # 将针对文件的修复任务发回给对应 dev
            for fix in result["fix_suggestions"]:
                event_bus.emit(f"dev_task:{fix['dev_id']}", {"type":"fix", "file_spec": fix["file_spec"], "issues": fix["issues"]})
        # 10) 收尾
        for dev in dev_threads:
            event_bus.emit(f"dev_task:{dev.agent_id}", {"type":"exit"})
        return str(repo.root)

    def _await_dev_round_done(self, event_bus, expected: int):
        ok = event_bus.wait_for_count("dev_done", expected=expected, timeout=300)
        if not ok:
            raise TimeoutError("Developers round timeout")