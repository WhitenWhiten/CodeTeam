from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from actions.request_briefing import RequestBriefingAction
from core.brief_manager import BriefManager
from core.repo_manager import RepoManager


class GitBriefCollaborationTests(unittest.TestCase):
    def test_commit_message_contains_structured_update_reason_json(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with tempfile.TemporaryDirectory() as tmp:
            repo = RepoManager(
                root=tmp,
                allowed_files_all={"main.py"},
                allowed_files_by_agent={"Dev-1": {"main.py"}},
                git_enabled=True,
            )
            repo.init_structure(["main.py"])
            repo.write_file("main.py", "def hello() -> str:\n    return 'hi'\n", agent_id="Dev-1")

            commit_hash = repo.commit_file(
                "main.py",
                {
                    "file_path": "main.py",
                    "change_type": "modify",
                    "functions_modified": [
                        {"name": "hello", "signature": "def hello() -> str:", "doc": ""}
                    ],
                    "classes_modified": [],
                    "compatibility_note": "Return type remains str.",
                    "affected_dependent_files": ["tests/test_main.py"],
                    "rationale": "tighten greeting implementation",
                    "related_files_brief_used": ["tests/test_main.py"],
                },
                "Dev-1",
            )

            self.assertIsNotNone(commit_hash)
            message = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            prefix = "update_reason: "
            reason_line = next(line for line in message.splitlines() if line.startswith(prefix))
            reason = json.loads(reason_line[len(prefix):])

            self.assertEqual(reason["target_file"], "main.py")
            self.assertEqual(reason["file_path"], "main.py")
            self.assertEqual(reason["modified_exported_symbols"], ["hello"])
            self.assertEqual(reason["compatibility_note"], "Return type remains str.")
            self.assertEqual(reason["affected_dependent_files"], ["tests/test_main.py"])
            self.assertEqual(reason["functions_modified"][0]["name"], "hello")

    def test_commit_file_only_commits_target_file(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with tempfile.TemporaryDirectory() as tmp:
            repo = RepoManager(
                root=tmp,
                allowed_files_all={"main.py", "other.py"},
                allowed_files_by_agent={"Dev-1": {"main.py", "other.py"}},
                git_enabled=True,
            )
            repo.init_structure(["main.py", "other.py"])
            repo.write_file("main.py", "print('main')\n", agent_id="Dev-1")
            repo.write_file("other.py", "print('other')\n", agent_id="Dev-1")
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True, text=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.local"], cwd=tmp, check=True)
            subprocess.run(["git", "add", "other.py"], cwd=tmp, check=True)

            commit_hash = repo.commit_file(
                "main.py",
                {
                    "file_path": "main.py",
                    "change_type": "modify",
                    "compatibility_note": "No caller impact.",
                    "affected_dependent_files": [],
                    "modified_exported_symbols": [],
                    "rationale": "update main only",
                    "related_files_brief_used": [],
                },
                "Dev-1",
            )

            self.assertIsNotNone(commit_hash)
            committed = subprocess.run(
                ["git", "show", "--pretty=", "--name-only", "HEAD"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()

            self.assertEqual(committed, ["main.py"])
            self.assertEqual(staged, ["other.py"])

    def test_agent_branch_commits_are_integrated_to_main(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with tempfile.TemporaryDirectory() as tmp:
            repo = RepoManager(
                root=tmp,
                allowed_files_all={"a.py", "b.py"},
                allowed_files_by_agent={"Dev-1": {"a.py"}, "Dev-2": {"b.py"}},
                git_enabled=True,
            )
            repo.init_structure(["a.py", "b.py"])

            repo.checkout_agent_branch("Dev-1")
            repo.write_file("a.py", "A = 1\n", agent_id="Dev-1")
            repo.commit_file("a.py", {"file_path": "a.py", "change_type": "modify", "related_files_brief_used": []}, "Dev-1")

            repo.checkout_agent_branch("Dev-2")
            repo.write_file("b.py", "B = 2\n", agent_id="Dev-2")
            repo.commit_file("b.py", {"file_path": "b.py", "change_type": "modify", "related_files_brief_used": []}, "Dev-2")

            current_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            main_files = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "main"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()

            self.assertEqual(current_branch, "main")
            self.assertCountEqual(main_files, ["a.py", "b.py"])

    def test_finalize_output_repository_cleans_runtime_artifacts_and_commits_tree(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        with tempfile.TemporaryDirectory() as tmp:
            repo = RepoManager(
                root=tmp,
                allowed_files_all={"main.py", "tests/test_main.py"},
                allowed_files_by_agent={"Dev-1": {"main.py"}},
                git_enabled=True,
            )
            repo.init_structure(["main.py", "tests/test_main.py"])
            repo.write_file("main.py", "VALUE = 1\n", agent_id="Dev-1")
            pycache = Path(tmp) / "__pycache__"
            pycache.mkdir()
            (pycache / "main.cpython-313.pyc").write_bytes(b"compiled")

            repo.finalize_output_repository()

            current_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            main_files = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "main"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()

            self.assertEqual(current_branch, "main")
            self.assertFalse(pycache.exists())
            self.assertCountEqual(main_files, ["main.py", "tests/test_main.py"])

    def test_brief_manager_returns_latest_update_reason(self):
        manager = BriefManager()
        update_reason = {
            "file_path": "shop/cart.py",
            "target_file": "shop/cart.py",
            "modified_exported_symbols": ["calculate_total"],
            "compatibility_note": "Callable contract preserved.",
            "affected_dependent_files": [],
        }

        manager.update_brief(
            "shop/cart.py",
            {
                "functions": [
                    {
                        "name": "calculate_total",
                        "signature": "def calculate_total(items: list[str]) -> float:",
                    }
                ],
                "classes": [],
            },
            update_reason=update_reason,
        )

        brief = manager.get_brief("shop/cart.py")

        self.assertIsNotNone(brief)
        self.assertEqual(brief["latest_update_reason"], update_reason)
        self.assertEqual(brief["compatibility_note"], "Callable contract preserved.")

    def test_request_briefing_returns_summary_without_full_file_content(self):
        manager = BriefManager()
        manager.update_brief(
            "shop/catalog.py",
            {
                "functions": [{"name": "get_price", "signature": "def get_price(name: str) -> float:"}],
                "classes": [],
                "source": "FULL SOURCE SHOULD NOT LEAK",
                "full_text": "FULL TEXT SHOULD NOT LEAK",
                "content": "CONTENT SHOULD NOT LEAK",
                "latest_update_reason": {
                    "file_path": "shop/catalog.py",
                    "compatibility_note": "No caller impact.",
                    "affected_dependent_files": [],
                    "modified_exported_symbols": ["get_price"],
                },
            },
        )

        brief = asyncio.run(
            RequestBriefingAction().run(target_file="shop/catalog.py", brief_manager=manager)
        )

        self.assertIn("functions", brief)
        self.assertIn("latest_update_reason", brief)
        self.assertNotIn("source", brief)
        self.assertNotIn("full_text", brief)
        self.assertNotIn("content", brief)
        self.assertNotIn("FULL SOURCE SHOULD NOT LEAK", json.dumps(brief))


if __name__ == "__main__":
    unittest.main()
