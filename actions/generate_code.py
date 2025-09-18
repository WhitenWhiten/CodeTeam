# actions/generate_code.py
from __future__ import annotations
from typing import Dict, Any
try:
    from metagpt.actions import Action
except ImportError:
    class Action:
        def __init__(self, name: str = ""):
            self.name = name
            self.llm = None
        async def run(self, *args, **kwargs):
            raise NotImplementedError

from core.ast_utils import to_brief

DEV_PROMPT_FALLBACK = """# FILE_PATH: {file_path}
你是资深开发工程师，负责实现单个文件。
约束：
- 只能写入目标文件：{file_path}；不得创建其他文件
- 参考的其他文件信息仅限简报(函数/类签名等)，不得请求源码
- 必须实现interfaces中声明的接口；可以添加必要的内部辅助函数
- 确保代码可被pytest执行；提供必要的类型注解与文档字符串
- 输出仅为该文件的完整源代码，无解释说明

职责：
{responsibilities}

interfaces：
{interfaces_pretty}

其他文件简报（只读）：
{briefs_pretty}
"""

class GenerateCodeAction(Action):
    name = "GenerateCodeAction"

    def __init__(self, llm=None):
        super().__init__(self.name)
        self.llm = llm

    def _build_prompt(self, file_spec: Dict[str, Any], briefs: Dict[str, Any]) -> str:
        functions = file_spec["interfaces"].get("functions", [])
        classes = file_spec["interfaces"].get("classes", [])
        iface_lines = []
        for f in functions:
            iface_lines.append(f"- function: {f['signature']}  # {f.get('doc','')}")
        for c in classes:
            iface_lines.append(f"- class: {c['name']}")
            if c.get("init_signature"):
                iface_lines.append(f"  init: {c['init_signature']}")
            for m in c.get("methods", []):
                iface_lines.append(f"  method: {m['signature']}  # {m.get('doc','')}")
        interfaces_pretty = "\n".join(iface_lines) if iface_lines else "(无)"

        brief_lines = []
        for path, b in briefs.items():
            brief_lines.append(f"* {path}")
            for f in b.get("functions", []):
                brief_lines.append(f"  - {f['signature']}")
            for c in b.get("classes", []):
                brief_lines.append(f"  - class {c['name']}")
                for m in c.get("methods", []):
                    brief_lines.append(f"    - {m['signature']}")
        briefs_pretty = "\n".join(brief_lines) if brief_lines else "(无)"

        tpl = DEV_PROMPT_FALLBACK
        return tpl.format(
            file_path=file_spec["path"],
            responsibilities=file_spec.get("responsibilities", ""),
            interfaces_pretty=interfaces_pretty,
            briefs_pretty=briefs_pretty,
        )

    async def run(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], llm, repo_manager, agent_id: str):
        prompt = self._build_prompt(file_spec, briefs)
        code = await llm.text(prompt)  # Mock/真实 LLM
        repo_manager.write_file(file_spec["path"], code)
        brief = to_brief(code)
        ur = {
            "file_path": file_spec["path"],
            "change_type": "create",
            "functions_added": brief["functions"],
            "classes_added": brief["classes"],
            "rationale": "initial implementation based on file_spec",
            "related_files_brief_used": list(briefs.keys())
        }
        repo_manager.commit_file(file_spec["path"], ur, agent_id)
        return brief