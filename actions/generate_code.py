# actions/generate_code.py
from __future__ import annotations
from pathlib import Path
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
from core.text_utils import strip_code_fences

DEV_PROMPT_FALLBACK = """# FILE_PATH: {file_path}
你是资深开发工程师。你的任务是实现或修复单个源码文件，并保证结果可直接写入目标仓库。

输出契约：
- 只输出目标文件的完整源码。
- 不要输出 Markdown、代码块、解释、注释性前言或任何额外文本。
- 不要创建、修改或提议修改除目标文件之外的其他文件。

实现约束：
- 目标文件路径固定为 `{file_path}`。
- 必须实现 `interfaces` 中声明的函数、类和方法；可以添加必要的内部辅助函数，但不要无故扩展对外接口。
- 只能依赖已提供的文件简报，不得假设能读取其他文件的完整源码。
- 代码必须兼容当前 PoC 的 Python + pytest 执行环境。
- 优先提供清晰的类型注解、稳定的公开接口和必要的文档字符串。

目标文件职责：
{responsibilities}

接口定义：
{interfaces_pretty}

其他文件简报（只读）：
{briefs_pretty}

修复上下文（若无则忽略）：
{issues_excerpt}
"""

class GenerateCodeAction(Action):
    def __init__(self, llm=None):
        try:
            # 兼容 metagpt.Action 的无参构造
            super().__init__()
        except TypeError:
            # 兼容我们自带的占位 Action(name: str="")
            super().__init__(name="GenerateCodeAction")
        self.llm = llm

    def _load_prompt_template(self) -> str:
        p = Path(__file__).resolve().parents[1] / "prompts" / "developer_prompt.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return DEV_PROMPT_FALLBACK

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

        tpl = self._load_prompt_template()
        return tpl.format(
            file_path=file_spec["path"],
            responsibilities=file_spec.get("responsibilities", ""),
            interfaces_pretty=interfaces_pretty,
            briefs_pretty=briefs_pretty,
            issues_excerpt=issues_excerpt or "(无)"
        )

    async def run(self, file_spec: Dict[str, Any], briefs: Dict[str, Any], llm, repo_manager, agent_id: str, issues: Optional[Dict[str, Any]] = None):
        prompt = self._build_prompt(file_spec, briefs, issues)
        raw_code = await llm.text(prompt)

        # 去除 Markdown/HTML 代码块围栏，确保写入与 AST 解析的源码干净
        code = strip_code_fences(raw_code)

        # change_type: 若文件已存在则为 modify，否则 create
        change_type = "modify" if repo_manager.exists(file_spec["path"]) else "create"

        # 写入代码（按 agent 权限）
        repo_manager.write_file(file_spec["path"], code, agent_id=agent_id)

        # 生成简报，容错处理语法错误（例如未完全移除围栏或生成代码不合法）
        try:
            brief = to_brief(code)
        except SyntaxError:
            brief = {"functions": [], "classes": [], "error": "syntax error in generated code"}

        ur = {
            "file_path": file_spec["path"],
            "change_type": change_type,
            "functions_added": [] if change_type == "modify" else brief.get("functions", []),
            "functions_modified": brief.get("functions", []) if change_type == "modify" else [],
            "functions_removed": [],
            "classes_added": [] if change_type == "modify" else brief.get("classes", []),
            "classes_modified": brief.get("classes", []) if change_type == "modify" else [],
            "classes_removed": [],
            "rationale": "fix implementation per QA feedback" if issues else "initial implementation based on file_spec",
            "related_files_brief_used": list(briefs.keys())
        }

        # 依赖现有 RepoManager 的 commit_file 实现
        repo_manager.commit_file(file_spec["path"], ur, agent_id)
        return brief
