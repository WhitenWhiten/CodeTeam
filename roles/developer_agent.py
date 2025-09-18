# roles/developer_agent.py
import threading
from metagpt.roles import Role
from actions.generate_code import GenerateCodeAction
from actions.request_briefing import RequestBriefingAction

class DeveloperAgent(Role, threading.Thread):
    def __init__(self, agent_id, assigned_files, llm, repo_manager, brief_manager, event_bus):
        Role.__init__(self, name=agent_id)
        threading.Thread.__init__(self, name=agent_id, daemon=True)
        self.agent_id = agent_id
        self.assigned_files = assigned_files
        self.llm = llm
        self.repo = repo_manager
        self.briefs = brief_manager
        self.event_bus = event_bus
        self.set_actions([GenerateCodeAction(llm=llm), RequestBriefingAction()])

    def run(self):
        while True:
            task = self.event_bus.take(f"dev_task:{self.agent_id}")  # 阻塞等待
            if task["type"] == "implement":
                file_spec = task["file_spec"]
                # 根据 dependencies 请求必要的简报
                briefs = {}
                for dep in file_spec.get("dependencies", []):
                    if dep not in self.assigned_files:
                        brief = self.run(RequestBriefingAction, target_file=dep, brief_manager=self.briefs)
                        if brief:
                            briefs[dep] = brief
                brief = self.run(GenerateCodeAction, file_spec=file_spec, briefs=briefs,
                                 llm=self.llm, repo_manager=self.repo, agent_id=self.agent_id)
                # 更新自己的简报
                self.briefs.update_brief(file_spec["path"], brief)
                self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_spec["path"]})
            elif task["type"] == "fix":
                file_spec = task["file_spec"]  # 可能仅含path，需在SDS中查回接口/职责（此处略）
                issues = task.get("issues", {})
                briefs = {}
                for dep in file_spec.get("dependencies", []):
                    if dep not in self.assigned_files:
                        brief = self.run(RequestBriefingAction, target_file=dep, brief_manager=self.briefs)
                        if brief:
                            briefs[dep] = brief
                # 可在prompt中注入issues.stack/output摘要作为上下文
                brief = self.run(GenerateCodeAction, file_spec=file_spec, briefs=briefs,
                                 llm=self.llm, repo_manager=self.repo, agent_id=self.agent_id)
                self.briefs.update_brief(file_spec["path"], brief)
                self.event_bus.emit("dev_done", {"agent_id": self.agent_id, "file": file_spec["path"]})
            elif task["type"] == "exit":
                break