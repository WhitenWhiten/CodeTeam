# core/llm.py
from __future__ import annotations
import json
from typing import Any, Dict

class LLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self._mode = getattr(cfg, "model", "mock")

    async def text(self, prompt: str) -> str:
        if self._mode == "mock":
            # 从提示中解析 FILE_PATH
            first_line = prompt.splitlines()[0].strip()
            file_path = ""
            if first_line.startswith("# FILE_PATH:"):
                file_path = first_line.split(":", 1)[1].strip()
            return self._mock_code(file_path)
        # TODO: 调用真实 LLM
        return ""

    async def structured_json(self, prompt: str, schema: str | Dict[str, Any] = None) -> Dict[str, Any]:
        if self._mode == "mock":
            if schema == "SDS":
                return self._mock_sds()
            if schema == "CTO_DECISION":
                return {"chosen_index": 0, "rationale": "Mock chooses the first SDS"}
        # TODO: 调用真实 LLM 并解析JSON
        return {}

    async def files(self, prompt: str) -> Dict[str, str]:
        if self._mode == "mock":
            return self._mock_tests()
        # TODO: 真实 LLM 返回多文件
        return {}

    # ---- Mock payloads ----
    def _mock_sds(self) -> Dict[str, Any]:
        return {
          "id": "sds-mock-001",
          "problem": "生成简单可测试的问候程序",
          "tech_stack": {
            "language": "python",
            "frameworks": [],
            "runtime": "python3.10",
            "test_framework": "pytest"
          },
          "repo_structure": [
            {"path": "main.py", "type": "file"},
            {"path": "app", "type": "dir", "children": [
              {"path": "utils.py", "type": "file"}
            ]},
            {"path": "tests", "type": "dir", "children": [
              {"path": "test_main.py", "type": "file"},
              {"path": "test_utils.py", "type": "file"}
            ]}
          ],
          "file_specs": [
            {
              "path": "main.py",
              "responsibilities": "应用入口；提供main(name:str='World')->str，调用app/utils.py的greet",
              "interfaces": {"functions": [
                {"name": "main", "signature": "def main(name: str = 'World') -> str:", "doc": "Return greeting"}
              ], "classes": []},
              "dependencies": ["app/utils.py"]
            },
            {
              "path": "app/utils.py",
              "responsibilities": "通用工具；提供greet(name:str)->str",
              "interfaces": {"functions": [
                {"name": "greet", "signature": "def greet(name: str) -> str:", "doc": "Return greeting text"}
              ], "classes": []},
              "dependencies": []
            }
          ],
          "dev_plan": [
            {"developer_id": "Dev-1", "file_paths": ["main.py"]},
            {"developer_id": "Dev-2", "file_paths": ["app/utils.py"]}
          ],
          "constraints": {},
          "notes": "tests目录由QA负责写入，但测试文件路径已在repo_structure中固定"
        }

    def _mock_code(self, file_path: str) -> str:
        if file_path == "app/utils.py":
            return '''"""
Utility functions.
"""
from typing import Any

def greet(name: str) -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"
'''
        if file_path == "main.py":
            return '''"""
Application entry point.
"""
from typing import Any
from app.utils import greet

def main(name: str = "World") -> str:
    """Return greeting by delegating to utils.greet."""
    message = greet(name)
    return message

if __name__ == "__main__":
    print(main())
'''
        # default empty
        return "# unknown file"

    def _mock_tests(self) -> Dict[str, str]:
        return {
          "tests/test_utils.py": '''from app.utils import greet

def test_greet_basic():
    assert greet("Alice") == "Hello, Alice!"
''',
          "tests/test_main.py": '''from main import main

def test_main_returns_message():
    assert main("Bob") == "Hello, Bob!"
'''
        }