# actions/request_briefing.py
from metagpt.actions import Action

class RequestBriefingAction(Action):
    async def run(self, target_file: str, brief_manager):
        brief = brief_manager.get_brief(target_file)
        return brief

# actions/generate_code.py
from metagpt.actions import Action
from core.ast_utils import to_brief

class GenerateCodeAction(Action):
    async def run(self, file_spec, briefs: dict, llm, repo_manager, agent_id):
        prompt = self._build_prompt(file_spec, briefs)
        code = await llm.text(prompt)
        repo_manager.write_file(file_spec["path"], code)
        brief = to_brief(code)  # 解析函数/类签名
        ur = {
          "file_path": file_spec["path"],
          "change_type": "create",
          "functions_added": brief["functions"],
          "classes_added": brief["classes"],
          "rationale": "initial implementation",
          "related_files_brief_used": list(briefs.keys())
        }
        repo_manager.commit_file(file_spec["path"], ur, agent_id)
        return brief

    def _build_prompt(self, file_spec, briefs):
        # 禁止创建新文件；仅实现 file_spec 中声明的接口；可添加必要私有辅助函数
        # 只能参考 briefs，而不能读取源码
        try:
            from metagpt.actions import Action
        except ImportError:
            class Action:
                def __init__(self, name: str = ""):
                    self.name = name
                    self.llm = None
            async def run(self, *args, **kwargs):
                raise NotImplementedError

        class RequestBriefingAction(Action):
            name = "RequestBriefingAction"
            async def run(self, target_file: str, brief_manager):
                return brief_manager.get_brief(target_file)
