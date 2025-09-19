# actions/generate_code.py (更新)
from __future__ import annotations
from typing import Dict, Any, Optional
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
你是资深开发工程师，负责实现或修复单个文件。
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

若为修复任务，以下为失败与日志片段（仅摘要）：
{issues_excerpt}
"""

class GenerateCodeAction(Action):
    def __init__(self, llm=None):
        try:
            super().__init__()  # 兼容 metagpt.Action
        except TypeError:
        # 兼容我们自带的占位 Action(name: str="")
            super().__init__(name="GenerateCodeAction")
        self.llm = llm

    def _build_prompt(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], issues: Optional[Dict[str, Any]] = None) -> str:
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

        issues_excerpt = ""
        if issues:
            stack = issues.get("stack", "")
            issues_excerpt = stack[:2000]  # 控制长度，避免爆上下文

        tpl = DEV_PROMPT_FALLBACK
        return tpl.format(
            file_path=file_spec["path"],
            responsibilities=file_spec.get("responsibilities", ""),
            interfaces_pretty=interfaces_pretty,
            briefs_pretty=briefs_pretty,
            issues_excerpt=issues_excerpt or "(无)"
        )

    async def run(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], llm, repo_manager, agent_id: str, issues: Optional[Dict[str, Any]] = None):
        prompt = self._build_prompt(file_spec, briefs, issues)
        code = await llm.text(prompt)
        # change_type: 若文件已存在则为 modify，否则 create
        change_type = "modify" if repo_manager.exists(file_spec["path"]) else "create"
        repo_manager.write_file(file_spec["path"], code, agent_id=agent_id)
        brief = to_brief(code)
        ur = {
            "file_path": file_spec["path"],
            "change_type": change_type,
            "functions_added": [] if change_type == "modify" else brief["functions"],
            "functions_modified": brief["functions"] if change_type == "modify" else [],
            "functions_removed": [],
            "classes_added": [] if change_type == "modify" else brief["classes"],
            "classes_modified": brief["classes"] if change_type == "modify" else [],
            "classes_removed": [],
            "rationale": "fix implementation per QA feedback" if issues else "initial implementation based on file_spec",
            "related_files_brief_used": list(briefs.keys())
        }
        repo_manager.commit_file(file_spec["path"], ur, agent_id)
        return brief
