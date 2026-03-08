from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag.rag_client import RAGClient
from runtime_adapters.python_runtime import PythonRuntime
from utils.failure_routing import build_fix_suggestions


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
            cfg = SimpleNamespace(top_k=3, corpus_file=str(corpus_path))
            client = RAGClient(cfg)

            results = client.query("fastapi shop checkout")

            self.assertTrue(results)
            self.assertEqual(results[0]["meta"]["source"], "demo/shop-fastapi")


class FailureRoutingTests(unittest.TestCase):
    def test_fix_suggestions_prefer_explicit_source_file(self):
        failures = [
            {
                "file_path": "tests/test_main.py",
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
            (root / "tests" / "test_main.py").write_text(
                "from main import checkout_total\n\n\ndef test_checkout_total():\n    assert checkout_total(['keyboard']) == 99.0\n",
                encoding="utf-8",
            )

            result = PythonRuntime().run_tests(str(root), "pytest -q")

            self.assertTrue(result["success"], result["output"])
            self.assertEqual(result["failures"], [])


if __name__ == "__main__":
    unittest.main()
