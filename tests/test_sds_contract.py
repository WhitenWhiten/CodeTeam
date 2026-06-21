from __future__ import annotations

import unittest

from actions.select_sds import SelectSDSAction
from core.schemas import validate_sds
from utils.sds_normalizer import normalize_sds_candidate


def _valid_sds() -> dict:
    return {
        "id": "sds-valid",
        "problem": "build a tiny app",
        "tech_stack": {
            "language": "python",
            "frameworks": [],
            "runtime": "python3.10",
            "test_framework": "pytest",
        },
        "repo_structure": [
            {"path": "main.py", "type": "file"},
            {"path": "shop", "type": "dir", "children": [{"path": "catalog.py", "type": "file"}]},
            {"path": "tests", "type": "dir", "children": [{"path": "test_app.py", "type": "file"}]},
        ],
        "file_specs": [
            {
                "path": "shop/catalog.py",
                "responsibilities": "Catalog data",
                "interfaces": {
                    "functions": [
                        {"name": "get_price", "signature": "def get_price(name: str) -> float:"}
                    ],
                    "classes": [],
                },
                "dependencies": [],
            },
            {
                "path": "main.py",
                "responsibilities": "Application entrypoint",
                "interfaces": {
                    "functions": [
                        {"name": "checkout_total", "signature": "def checkout_total(names: list[str]) -> float:"}
                    ],
                    "classes": [],
                },
                "dependencies": ["shop/catalog.py:get_price"],
            },
        ],
        "dev_plan": [
            {"developer_id": "Dev-1", "file_paths": ["shop/catalog.py"]},
            {"developer_id": "Dev-2", "file_paths": ["main.py"]},
        ],
    }


class SDSContractTests(unittest.TestCase):
    def test_invalid_dependency_fails_contract_validation(self):
        sds = _valid_sds()
        sds["file_specs"][1]["dependencies"] = ["shop/missing.py"]

        with self.assertRaisesRegex(ValueError, "dependency does not point"):
            validate_sds(sds)

    def test_file_dependency_cycle_fails_contract_validation(self):
        sds = _valid_sds()
        sds["file_specs"][0]["dependencies"] = ["main.py"]

        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            validate_sds(sds)

    def test_paper_field_aliases_are_normalized(self):
        paper_sds = {
            "id": "paper-sds",
            "problem": "build a tiny app",
            "tech_stack": {
                "language": "python",
                "frameworks": [],
                "runtime": "python3.10",
                "test_framework": "pytest",
            },
            "repo_tree": ["app.py", "pricing.py", "tests/test_app.py"],
            "files": [
                {
                    "path": "pricing.py",
                    "owner": "Dev-1",
                    "responsibility": "Price lookup",
                    "public_api": {
                        "functions": [{"name": "price_for", "signature": "def price_for(name: str) -> float:"}],
                        "classes": [],
                    },
                },
                {
                    "path": "app.py",
                    "owner": "Dev-2",
                    "responsibility": "App entrypoint",
                    "public_api": {
                        "functions": [{"name": "total", "signature": "def total(names: list[str]) -> float:"}],
                        "classes": [],
                    },
                    "depends_on": ["price_for"],
                },
            ],
            "developer_plan": {
                "Dev-1": ["pricing.py"],
                "Dev-2": ["app.py"],
            },
        }

        normalized = normalize_sds_candidate(paper_sds)

        self.assertIn("repo_structure", normalized)
        self.assertIn("file_specs", normalized)
        self.assertIn("dev_plan", normalized)
        self.assertEqual(normalized["file_specs"][1]["dependencies"], ["price_for"])
        validate_sds(normalized)

    def test_illustrative_paper_schema_shape_is_accepted(self):
        paper_sds = {
            "id": "paper-schema",
            "problem": "build an API wrapper",
            "tech_stack": {"language": "Python", "frameworks": ["Flask"], "runtime": "python3.10", "test_framework": "pytest"},
            "repo_tree": ["src/core.py", "src/api.py", "tests/test_api.py"],
            "dependencies": ["flask>=2.0", "pytest"],
            "developer_plan": {
                "num_developers": 2,
                "owners": [
                    {"id": 0, "files": ["src/core.py"]},
                    {"id": 1, "files": ["src/api.py"]},
                ],
            },
            "files": [
                {
                    "path": "src/core.py",
                    "purpose": "domain objects",
                    "responsibility": "domain objects",
                    "public_api": {"functions": [], "classes": [{"name": "User", "methods": []}]},
                    "owner": 0,
                },
                {
                    "path": "src/api.py",
                    "purpose": "HTTP API wrappers",
                    "responsibility": "HTTP API wrappers",
                    "public_api": {
                        "functions": [{"name": "fetch_user", "signature": "def fetch_user(user_id: str) -> User:"}],
                        "classes": [],
                    },
                    "depends_on": ["src/core.py::User"],
                    "owner": 1,
                },
            ],
        }

        normalized = normalize_sds_candidate(paper_sds)

        self.assertEqual(normalized["dev_plan"][0]["developer_id"], "0")
        self.assertEqual(normalized["file_specs"][1]["owner"], "1")
        self.assertEqual(normalized["file_specs"][1]["dependencies"], ["src/core.py::User"])
        validate_sds(normalized)


class _DecisionLLM:
    async def structured_json(self, prompt, schema=None):
        return {
            "chosen_index": 99,
            "rationale": "bad index should fall back",
            "scores": {
                "structural_validity": 2,
                "interface_consistency": 2,
                "implementability": 1,
                "developer_plan": 2,
            },
        }


class SelectSDSContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_cto_selection_filters_invalid_candidates_and_falls_back_to_first_valid(self):
        invalid = _valid_sds()
        invalid["id"] = "invalid"
        invalid["file_specs"][1]["dependencies"] = ["missing.py"]
        valid = _valid_sds()
        valid["id"] = "valid"

        result = await SelectSDSAction(llm=_DecisionLLM()).run("build app", [invalid, valid])

        self.assertEqual(result["chosen_sds"]["id"], "valid")
        self.assertEqual(result["rationale"], "bad index should fall back")
        self.assertEqual(result["scores"]["structural_validity"], 2)


if __name__ == "__main__":
    unittest.main()
