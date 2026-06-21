from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import bootstrap
from app.config import load_config
from orchestrator.architect_diversity import build_architect_profiles, update_claimed_summary
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync
from rag.rag_client import RAGClient


class ArchitectDiversityTests(unittest.TestCase):
    def test_profiles_are_seeded_and_have_distinct_preferences(self):
        first = build_architect_profiles(4, seed=7)
        second = build_architect_profiles(4, seed=7)

        self.assertEqual(first, second)
        self.assertEqual(len({p.preference for p in first}), 4)

    def test_claimed_summary_exposes_only_coarse_modules_and_intents(self):
        summary = update_claimed_summary(
            [
                {
                    "problem": "build a checkout system",
                    "repo_structure": [
                        {"path": "shop", "type": "dir", "children": []},
                        {"path": "main.py", "type": "file"},
                    ],
                }
            ]
        )

        self.assertIn("shop", summary)
        self.assertIn("main.py", summary)
        self.assertIn("checkout", summary)


class RAGFilteringTests(unittest.TestCase):
    def test_query_returns_distinct_non_duplicate_design_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            corpus.write_text(
                json.dumps(
                    [
                        {
                            "full_name": "demo/shop",
                            "readme": "Python shop checkout cart catalog",
                            "tree": "[shop[catalog.py, cart.py]]",
                        },
                        {
                            "full_name": "demo/shop",
                            "readme": "Python shop checkout cart catalog duplicate",
                            "tree": "[shop[catalog.py, cart.py]]",
                        },
                        {
                            "full_name": "demo/blog",
                            "readme": "Python blog renderer",
                            "tree": "[blog[main.py]]",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            client = RAGClient(
                SimpleNamespace(
                    corpus_file=str(corpus),
                    top_k=3,
                    distinct_sources=True,
                    similarity_threshold=0.99,
                )
            )

            results = client.query("python shop checkout catalog")

            sources = [item["meta"]["source"] for item in results]
            self.assertEqual(sources.count("demo/shop"), 1)
            self.assertTrue(all(item["meta"]["retrieval_kind"] == "design_hint" for item in results))


class WorkflowArtifactTests(unittest.TestCase):
    def test_mock_workflow_writes_planning_and_qa_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.workspace = str(Path(tmp) / "workspace")
            cfg.artifacts_dir = str(Path(tmp) / "artifacts")
            cfg.artifacts_enabled = True
            cfg.llm.provider = "mock"
            cfg.architect_seed = 3

            ctx = bootstrap(cfg)
            wf = MultiAgentCodegenWorkflowAsync(ctx)
            import asyncio

            repo_path = asyncio.run(wf.run(question=cfg.user_question))

            self.assertTrue(Path(repo_path).exists())
            self.assertTrue((Path(cfg.artifacts_dir) / "requirements" / "normalized_requirements.md").exists())
            self.assertTrue((Path(cfg.artifacts_dir) / "planning" / "architect_candidates.json").exists())
            self.assertTrue((Path(cfg.artifacts_dir) / "planning" / "cto_decision.json").exists())
            self.assertTrue((Path(cfg.artifacts_dir) / "qa" / "round_0.json").exists())

            candidates = json.loads((Path(cfg.artifacts_dir) / "planning" / "architect_candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(len(candidates), 4)
            self.assertIn("design_preference", candidates[0])
            self.assertIn("claimed_summary", candidates[0])


if __name__ == "__main__":
    unittest.main()
