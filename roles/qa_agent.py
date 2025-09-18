# roles/qa_agent.py
from metagpt.roles import Role
from actions.generate_tests import GenerateTestsAction
from actions.run_tests import RunTestsAction

class QAAgent(Role):
    def __init__(self, llm, repo_manager, runtime_adapter, event_bus, sds=None):
        super().__init__(name="QA")
        self.llm = llm
        self.repo = repo_manager
        self.adapter = runtime_adapter
        self.event_bus = event_bus
        self.sds = sds
        self.file_owner = {}
        if sds:
            for a in sds.dev_plan:
                for f in a.file_paths:
                    self.file_owner[f] = a.developer_id
        self.set_actions([GenerateTestsAction(llm=llm), RunTestsAction()])

    async def run_and_feedback(self):
        result = await self.run(RunTestsAction, repo_root=str(self.repo.root), run_command=self.run_command, runtime_adapter=self.adapter)
        fix_suggestions = []
        for fail in result.get("failures", []):
            fp = fail["file_path"]
            # 简化：如果失败发生在tests/，尝试从堆栈中找源文件路径；否则直接路由到全部源文件负责人
            owner = self.file_owner.get(fp)
            if not owner:
                # 广播到所有责任人（保守策略）
                for f, dev in self.file_owner.items():
                    fix_suggestions.append({"dev_id": dev, "file_spec": {"path": f}, "issues": fail})
            else:
                fix_suggestions.append({"dev_id": owner, "file_spec": {"path": fp}, "issues": fail})
        result["fix_suggestions"] = fix_suggestions
        self.event_bus.emit("qa_result", result)
        return result