from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.bootstrap import bootstrap
from app.config import load_config
from actions.generate_sds import ARCHITECT_PROMPT_FALLBACK
from actions.generate_code import DEV_PROMPT_FALLBACK, GenerateCodeAction
from actions.generate_tests import GenerateTestsAction, QA_PROMPT_FALLBACK
from actions.select_sds import CTO_PROMPT_FALLBACK, SelectSDSAction
from core.llm import LLMClient
from core.requirements_preprocessor import preprocess_requirements
from core.repo_manager import RepoManager
from rag.rag_client import RAGClient
from runtime_adapters.python_runtime import PythonRuntime
from utils.failure_routing import build_fix_suggestions
from utils.runtime_dev_plan import build_fixed_random_dev_plan, build_runtime_sds_json


class RAGClientTests(unittest.TestCase):
    def test_query_returns_ranked_results_from_local_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus_path = Path(tmp) / "corpus.json"
            corpus_path.write_text(
                json.dumps(
                    [
                        {
                            "full_name": "demo/shop-fastapi",
                            "readme": "FastAPI online shop with cart and checkout support.",
                            "tree": "[app[main.py, cart.py, catalog.py]]",
                        },
                        {
                            "full_name": "demo/blog",
                            "readme": "Static blog generator.",
                            "tree": "[blog[main.py]]",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            cfg = SimpleNamespace(top_k=3, corpus_file=str(corpus_path), index_backend="lexical")
            client = RAGClient(cfg)

            results = client.query("fastapi shop checkout")

            self.assertTrue(results)
            self.assertEqual(results[0]["meta"]["source"], "demo/shop-fastapi")


class RequirementsPreprocessorTests(unittest.TestCase):
    def test_preprocess_requirements_removes_readme_noise_and_keeps_actionable_blocks(self):
        raw = """# Demo Project

[![build](https://example.com/badge.svg)](https://example.com)
![logo](logo.png)

## Features
- Catalog browsing
  - Cart checkout

```bash
pytest -q
```

```text
purely decorative banner
```

## Changelog
- v1.0 old release note

## API
Use `checkout_total(items)`.
"""

        normalized = preprocess_requirements(raw)

        self.assertIn("# Demo Project", normalized)
        self.assertIn("- Catalog browsing", normalized)
        self.assertIn("- Cart checkout", normalized)
        self.assertIn("```bash\npytest -q\n```", normalized)
        self.assertIn("## API", normalized)
        self.assertNotIn("badge.svg", normalized)
        self.assertNotIn("logo.png", normalized)
        self.assertNotIn("purely decorative banner", normalized)
        self.assertNotIn("old release note", normalized)


class FailureRoutingTests(unittest.TestCase):
    def test_fix_suggestions_prefer_explicit_source_file(self):
        failures = [
            {
                "file_path": "tests/test_checkout.py",
                "source_file": "shop/cart.py",
                "message": "assertion failed",
                "stack": "shop/cart.py:10",
            }
        ]
        file_owner = {
            "main.py": "Dev-1",
            "shop/catalog.py": "Dev-2",
            "shop/cart.py": "Dev-3",
        }

        suggestions = build_fix_suggestions(failures, file_owner)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["dev_id"], "Dev-3")
        self.assertEqual(suggestions[0]["file_path"], "shop/cart.py")


class RuntimeFallbackTests(unittest.TestCase):
    def test_python_runtime_runs_pytest_style_tests_without_pytest_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shop").mkdir()
            (root / "tests").mkdir()
            (root / "shop" / "__init__.py").write_text("", encoding="utf-8")
            (root / "shop" / "catalog.py").write_text(
                "def get_price(name: str) -> float:\n    return {'keyboard': 99.0}[name]\n",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from shop.catalog import get_price\n\n\ndef checkout_total(item_names: list[str]) -> float:\n    return sum(get_price(name) for name in item_names)\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_checkout.py").write_text(
                "from main import checkout_total\n\n\ndef test_checkout_total():\n    assert checkout_total(['keyboard']) == 99.0\n",
                encoding="utf-8",
            )

            result = PythonRuntime().run_tests(str(root), "pytest -q")

            self.assertTrue(result["success"], result["output"])
            self.assertEqual(result["failures"], [])


class PromptAlignmentTests(unittest.TestCase):
    def test_architect_prompt_does_not_hardcode_stale_test_file_names(self):
        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "architect_prompt.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")

        for content in (prompt_text, ARCHITECT_PROMPT_FALLBACK):
            self.assertNotIn("tests/test_main.py and tests/test_utils.py are required", content)
            self.assertNotIn("must include tests/test_main.py", content)
            self.assertIn("do not hardcode `tests/test_main.py` or `tests/test_utils.py`", content)
            self.assertIn("business source directories and a `tests/` directory", content)

    def test_cto_prompt_matches_current_execution_constraints(self):
        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "cto_prompt.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")

        for content in (prompt_text, CTO_PROMPT_FALLBACK):
            self.assertIn("The current PoC supports only `python + pytest`", content)
            self.assertIn("business modules, key flows, and boundary conditions", content)
            self.assertNotIn("If the selected tech stack is not python", content)

    def test_qa_prompt_uses_behavior_based_test_naming(self):
        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "qa_prompt.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")

        for content in (prompt_text, QA_PROMPT_FALLBACK):
            self.assertIn("tests/test_checkout.py", content)
            self.assertIn("Do not hardcode templated names such as `tests/test_main.py` or `tests/test_utils.py`", content)
            self.assertIn("\"setup_commands\": []", content)

    def test_cto_and_qa_prompt_templates_render_without_format_errors(self):
        cto_prompt = SelectSDSAction()._build_prompt(
            question="build an online shop",
            sds_list=[{"id": "s1", "tech_stack": {"language": "python"}}],
            rag_client=None,
        )
        qa_prompt = GenerateTestsAction()._build_prompt(
            {
                "id": "s1",
                "problem": "build an online shop",
                "tech_stack": {
                    "language": "python",
                    "frameworks": [],
                    "runtime": "python3.10",
                    "test_framework": "pytest",
                },
                "repo_structure": [],
                "file_specs": [],
                "dev_plan": [],
            }
        )

        self.assertIn('"chosen_index"', cto_prompt)
        self.assertIn('"setup_commands": []', qa_prompt)

    def test_developer_prompt_is_externalized_and_renders(self):
        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "developer_prompt.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")

        for content in (prompt_text, DEV_PROMPT_FALLBACK):
            self.assertIn("# FILE_PATH: {file_path}", content)
            self.assertIn("Output only the complete source code for the target file", content)
            self.assertIn("The target file path is fixed as `{file_path}`", content)

        prompt = GenerateCodeAction()._build_prompt(
            file_spec={
                "path": "shop/cart.py",
                "responsibilities": "Calculate the cart total from product names and a price lookup function",
                "interfaces": {
                    "functions": [
                        {
                            "name": "calculate_total",
                            "signature": "def calculate_total(item_names: list[str], price_lookup: callable) -> float:",
                            "doc": "Return the total price.",
                        }
                    ],
                    "classes": [],
                },
            },
            briefs={"shop/catalog.py": {"functions": [{"signature": "def get_price(name: str) -> float:"}], "classes": []}},
            issues={"stack": "AssertionError in tests/test_checkout.py"},
        )

        self.assertIn("# FILE_PATH: shop/cart.py", prompt)
        self.assertIn("Calculate the cart total from product names and a price lookup function", prompt)
        self.assertIn("def calculate_total(item_names: list[str], price_lookup: callable) -> float:", prompt)
        self.assertIn("AssertionError in tests/test_checkout.py", prompt)


class MockAlignmentTests(unittest.TestCase):
    def test_mock_sds_and_tests_use_checkout_named_flow_test(self):
        llm = LLMClient(SimpleNamespace(provider="mock"))

        sds = llm._mock_sds()
        repo_files = set()
        for node in sds["repo_structure"]:
            if node["type"] == "file":
                repo_files.add(node["path"])
            else:
                for child in node.get("children", []):
                    repo_files.add(f"{node['path']}/{child['path']}")

        bundle = llm._mock_test_bundle()

        self.assertIn("tests/test_checkout.py", bundle["tests"])
        self.assertNotIn("tests/test_main.py", bundle["tests"])
        self.assertIn("tests/test_checkout.py", repo_files)
        self.assertNotIn("tests/test_main.py", repo_files)


class ConfigAndFeatureToggleTests(unittest.TestCase):
    def test_paper_aligned_defaults_are_exposed(self):
        cfg = load_config()

        self.assertEqual(cfg.architects, 4)
        self.assertEqual(cfg.rag.top_k, 5)
        self.assertEqual(cfg.rag.embedding_model, "BAAI/bge-m3")
        self.assertEqual(cfg.rag.index_backend, "faiss_hnsw")
        self.assertEqual(cfg.rag.chunk_tokens, 768)
        self.assertEqual(cfg.rag.chunk_overlap, 128)
        self.assertEqual(cfg.llm.model, "Qwen2.5-72B-Instruct")
        self.assertEqual(cfg.llm.top_p, 0.95)
        self.assertEqual(cfg.llm.max_tokens, 8192)
        self.assertTrue(cfg.preprocess_requirements)

    def test_load_config_parses_feature_flags_and_rag_off_disables_bootstrap_rag(self):
        with patch.dict(
            os.environ,
            {
                "CODETEAM_RAG_ENABLED": "0",
                "CODETEAM_GIT_COLLAB_ENABLED": "0",
                "CODETEAM_DYNAMIC_DEVELOPER_ASSIGNMENT_ENABLED": "0",
                "CODETEAM_FIXED_DEVELOPER_AGENTS": "4",
                "CODETEAM_DEVELOPER_ASSIGNMENT_SEED": "7",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertFalse(cfg.rag.enabled)
        self.assertFalse(cfg.git.enabled)
        self.assertFalse(cfg.developer_allocation.dynamic_enabled)
        self.assertEqual(cfg.developer_allocation.fixed_agents, 4)
        self.assertEqual(cfg.developer_allocation.assignment_seed, 7)

        ctx = bootstrap(cfg)
        self.assertIsNone(ctx.rag)


class GitCollaborationToggleTests(unittest.TestCase):
    def test_git_disabled_prevents_repo_manager_from_initializing_or_committing_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = RepoManager(
                root=tmp,
                allowed_files_all={"main.py"},
                allowed_files_by_agent={"Dev-1": {"main.py"}},
                git_enabled=False,
            )
            repo.init_structure(["main.py"])
            repo.write_file("main.py", "print('hello')\n", agent_id="Dev-1")

            self.assertIsNone(repo.commit_file("main.py", {"change_type": "modify"}, "Dev-1"))
            self.assertIsNone(repo.commit_all("should not commit"))
            self.assertFalse((Path(tmp) / ".git").exists())

            with self.assertRaises(PermissionError):
                repo._git("status")


class DeveloperAllocationToggleTests(unittest.TestCase):
    def test_fixed_random_dev_plan_uses_four_agents_and_covers_each_file_once(self):
        plan = build_fixed_random_dev_plan(
            ["main.py", "shop/catalog.py", "shop/cart.py"],
            fixed_agent_count=4,
            assignment_seed=7,
        )

        self.assertEqual([item.developer_id for item in plan], ["Dev-1", "Dev-2", "Dev-3", "Dev-4"])
        assigned = [path for item in plan for path in item.file_paths]
        self.assertCountEqual(assigned, ["main.py", "shop/catalog.py", "shop/cart.py"])
        self.assertEqual(sum(1 for item in plan if not item.file_paths), 1)

    def test_runtime_sds_json_overrides_architect_dev_plan_when_dynamic_disabled(self):
        sds_json = {
            "id": "sds-1",
            "problem": "shop",
            "tech_stack": {"language": "python", "frameworks": [], "runtime": "python3.10", "test_framework": "pytest"},
            "repo_structure": [],
            "file_specs": [
                {"path": "main.py", "responsibilities": "", "interfaces": {"functions": [], "classes": []}, "dependencies": []},
                {"path": "shop/catalog.py", "responsibilities": "", "interfaces": {"functions": [], "classes": []}, "dependencies": []},
                {"path": "shop/cart.py", "responsibilities": "", "interfaces": {"functions": [], "classes": []}, "dependencies": []},
            ],
            "dev_plan": [{"developer_id": "Architect-Dev", "file_paths": ["main.py", "shop/catalog.py", "shop/cart.py"]}],
        }

        runtime_sds = build_runtime_sds_json(
            sds_json,
            dynamic_enabled=False,
            fixed_agent_count=4,
            assignment_seed=3,
        )

        self.assertEqual(len(runtime_sds["dev_plan"]), 4)
        self.assertEqual(runtime_sds["dev_plan"][0]["developer_id"], "Dev-1")
        self.assertNotEqual(runtime_sds["dev_plan"], sds_json["dev_plan"])
        self.assertIn("runtime override: developer allocation fixed to 4 agents", runtime_sds["notes"])
        assigned = [path for item in runtime_sds["dev_plan"] for path in item["file_paths"]]
        self.assertCountEqual(assigned, ["main.py", "shop/catalog.py", "shop/cart.py"])


if __name__ == "__main__":
    unittest.main()
