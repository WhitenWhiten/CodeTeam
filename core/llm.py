# core/llm.py
from __future__ import annotations
from typing import Any, Dict

class LLMClient:
    def __init__(self, cfg):
        self.cfg = cfg
        provider = getattr(cfg, "provider", "mock")
        self._mode = "mock" if provider == "mock" else getattr(cfg, "model", "mock")

    async def text(self, prompt: str) -> str:
        if self._mode == "mock":
            # Parse FILE_PATH from the prompt.
            first_line = prompt.splitlines()[0].strip()
            file_path = ""
            if first_line.startswith("# FILE_PATH:"):
                file_path = first_line.split(":", 1)[1].strip()
            return self._mock_code(file_path)
        # TODO: call the real LLM.
        return ""

    # working on this method
    async def structured_json(self, prompt: str, schema: str | Dict[str, Any] = None) -> Dict[str, Any]:
        if self._mode == "mock":
            if schema == "SDS":
                return self._mock_sds()
            if schema == "CTO_DECISION":
                return {"chosen_index": 0, "rationale": "Mock chooses the first SDS"}
            if schema == "QA_TEST_BUNDLE":
                return self._mock_test_bundle()
        # TODO: call the real LLM and parse JSON.
        return {}

    async def files(self, prompt: str) -> Dict[str, str]:
        if self._mode == "mock":
            return self._mock_tests()
        # TODO: return multiple files from the real LLM.
        return {}

    # ---- Mock payloads ----
    def _mock_sds(self) -> Dict[str, Any]:
        return {
          "id": "sds-mock-001",
          "problem": "Build a simplified online shop program",
          "tech_stack": {
            "language": "python",
            "frameworks": [],
            "runtime": "python3.10",
            "test_framework": "pytest"
          },
          "repo_structure": [
            {"path": "main.py", "type": "file"},
            {"path": "shop", "type": "dir", "children": [
              {"path": "__init__.py", "type": "file"},
              {"path": "catalog.py", "type": "file"},
              {"path": "cart.py", "type": "file"}
            ]},
            {"path": "tests", "type": "dir", "children": [
              {"path": "test_catalog.py", "type": "file"},
              {"path": "test_cart.py", "type": "file"},
              {"path": "test_checkout.py", "type": "file"}
            ]}
          ],
          "file_specs": [
            {
              "path": "main.py",
              "responsibilities": "Application entry point; provide checkout_total(item_names: list[str]) -> float by combining catalog and cart logic",
              "interfaces": {"functions": [
                {"name": "checkout_total", "signature": "def checkout_total(item_names: list[str]) -> float:", "doc": "Return the total price for selected products"}
              ], "classes": []},
              "dependencies": ["shop/catalog.py", "shop/cart.py"]
            },
            {
              "path": "shop/catalog.py",
              "responsibilities": "Product catalog module; provide the base product list and name-based price lookup",
              "interfaces": {"functions": [
                {"name": "list_products", "signature": "def list_products() -> list[dict]:", "doc": "Return the product catalog"},
                {"name": "get_price", "signature": "def get_price(name: str) -> float:", "doc": "Return the price of a named product"}
              ], "classes": []},
              "dependencies": []
            },
            {
              "path": "shop/cart.py",
              "responsibilities": "Cart module; calculate the total price from product names and catalog prices",
              "interfaces": {"functions": [
                {"name": "calculate_total", "signature": "def calculate_total(item_names: list[str], price_lookup: callable) -> float:", "doc": "Calculate a cart total from a lookup function"}
              ], "classes": []},
              "dependencies": ["shop/catalog.py"]
            }
          ],
          "dev_plan": [
            {"developer_id": "Dev-1", "file_paths": ["main.py"]},
            {"developer_id": "Dev-2", "file_paths": ["shop/catalog.py"]},
            {"developer_id": "Dev-3", "file_paths": ["shop/cart.py"]}
          ],
          "constraints": {},
          "notes": "The tests directory is written by QA; three Developers own the entry point, product catalog, and cart logic respectively."
        }

    def _mock_code(self, file_path: str) -> str:
        if file_path == "shop/catalog.py":
            return '''"""
Catalog data for the demo online shop.
"""
from __future__ import annotations

PRODUCTS = [
    {"name": "keyboard", "price": 99.0},
    {"name": "mouse", "price": 49.0},
    {"name": "monitor", "price": 199.0},
]


def list_products() -> list[dict]:
    """Return the available product catalog."""
    return [dict(item) for item in PRODUCTS]


def get_price(name: str) -> float:
    """Return the price of a known product."""
    for product in PRODUCTS:
        if product["name"] == name:
            return float(product["price"])
    raise KeyError(f"unknown product: {name}")
'''
        if file_path == "shop/cart.py":
            return '''"""
Cart helpers for the demo online shop.
"""
from __future__ import annotations


def calculate_total(item_names: list[str], price_lookup: callable) -> float:
    """Calculate the total price of all requested items."""
    total = 0.0
    for item_name in item_names:
        total += float(price_lookup(item_name))
    return total
'''
        if file_path == "main.py":
            return '''"""
Application entry point for the demo online shop.
"""
from __future__ import annotations

from shop.cart import calculate_total
from shop.catalog import get_price


def checkout_total(item_names: list[str]) -> float:
    """Return the cart total for the provided product names."""
    return calculate_total(item_names, get_price)

if __name__ == "__main__":
    sample = ["keyboard", "mouse"]
    print(checkout_total(sample))
'''
        # default empty
        return "# unknown file"

    def _mock_tests(self) -> Dict[str, str]:
        return dict(self._mock_test_bundle()["tests"])

    def _mock_test_bundle(self) -> Dict[str, Any]:
        return {
            "tests": {
                "tests/test_catalog.py": '''from shop.catalog import get_price, list_products

def test_catalog_lists_products():
    names = [item["name"] for item in list_products()]
    assert names == ["keyboard", "mouse", "monitor"]

def test_catalog_price_lookup():
    assert get_price("mouse") == 49.0
''',
                "tests/test_checkout.py": '''from main import checkout_total

def test_checkout_total():
    assert checkout_total(["keyboard", "mouse"]) == 148.0
''',
                "tests/test_cart.py": '''from shop.cart import calculate_total

def test_cart_total_uses_lookup():
    prices = {"keyboard": 99.0, "mouse": 49.0}
    total = calculate_total(["keyboard", "mouse"], prices.__getitem__)
    assert total == 148.0
''',
            },
            "run_command": "pytest -q",
        }
