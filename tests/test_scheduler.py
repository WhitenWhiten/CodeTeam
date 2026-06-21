from __future__ import annotations

import unittest
from types import SimpleNamespace

from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync
from orchestrator.scheduler import DependencyScheduler, SchedulerError


def spec(path: str, dependencies: list[str] | None = None) -> dict:
    return {
        "path": path,
        "responsibilities": "",
        "interfaces": {"functions": [], "classes": []},
        "dependencies": dependencies or [],
    }


class DependencySchedulerTests(unittest.TestCase):
    def test_owner_ready_queue_uses_depth_fanout_and_sds_order_priority(self):
        scheduler = DependencyScheduler(
            [
                spec("wide.py"),
                spec("deep.py"),
                spec("mid.py", ["deep.py"]),
                spec("leaf.py", ["mid.py"]),
                spec("wide_user_a.py", ["wide.py"]),
                spec("wide_user_b.py", ["wide.py"]),
            ],
            [{"developer_id": "Dev-1", "file_paths": [
                "wide.py",
                "deep.py",
                "mid.py",
                "leaf.py",
                "wide_user_a.py",
                "wide_user_b.py",
            ]}],
        )

        dispatched = scheduler.dispatch_ready()

        self.assertEqual([item.file_path for item in dispatched], ["deep.py"])
        self.assertEqual(scheduler.priority_for("deep.py"), (2, 1, -1))
        self.assertEqual(scheduler.priority_for("wide.py"), (1, 2, 0))

    def test_completion_unlocks_downstream_and_ignores_external_dependencies(self):
        scheduler = DependencyScheduler(
            [
                spec("a.py", ["requests"]),
                spec("b.py", ["a.py"]),
            ],
            [
                {"developer_id": "Dev-1", "file_paths": ["a.py"]},
                {"developer_id": "Dev-2", "file_paths": ["b.py"]},
            ],
        )

        self.assertEqual(scheduler.ready_files(), ["a.py"])
        dispatched = scheduler.dispatch_ready()
        self.assertEqual([item.file_path for item in dispatched], ["a.py"])

        scheduler.complete("a.py")

        self.assertEqual(scheduler.ready_files(), ["b.py"])
        self.assertEqual(scheduler.dispatch_ready()[0].file_path, "b.py")

    def test_cycle_raises_clear_scheduler_error(self):
        with self.assertRaisesRegex(SchedulerError, "cycle detected"):
            DependencyScheduler(
                [
                    spec("a.py", ["b.py"]),
                    spec("b.py", ["a.py"]),
                ],
                [{"developer_id": "Dev-1", "file_paths": ["a.py", "b.py"]}],
            )

    def test_requeue_from_public_api_change_requeues_direct_dependents(self):
        scheduler = DependencyScheduler(
            [
                spec("api.py"),
                spec("consumer.py", ["api.py"]),
            ],
            [
                {"developer_id": "Dev-1", "file_paths": ["api.py"]},
                {"developer_id": "Dev-2", "file_paths": ["consumer.py"]},
            ],
        )
        for item in scheduler.dispatch_ready():
            scheduler.complete(item.file_path)
        for item in scheduler.dispatch_ready():
            scheduler.complete(item.file_path)

        payloads = scheduler.requeue_from_fixes(
            [{"file_path": "api.py", "issues": {}, "public_api_changed": True}]
        )

        self.assertCountEqual(scheduler.ready_files(), ["api.py"])
        self.assertIn("consumer.py", payloads)
        scheduler.complete(scheduler.dispatch_ready()[0].file_path)
        self.assertEqual(scheduler.ready_files(), ["consumer.py"])


class WorkflowBudgetTests(unittest.TestCase):
    def test_resource_limit_check_raises_for_token_budget(self):
        cfg = SimpleNamespace(max_wall_clock_seconds=None, max_token_budget=10)
        llm = SimpleNamespace(total_tokens=11)
        wf = MultiAgentCodegenWorkflowAsync(SimpleNamespace(cfg=cfg, llm=llm))

        with self.assertRaisesRegex(RuntimeError, "token budget"):
            wf._check_resource_limits()

    def test_resource_limit_check_raises_for_wall_clock_budget(self):
        cfg = SimpleNamespace(max_wall_clock_seconds=1, max_token_budget=None)
        llm = SimpleNamespace(total_tokens=0)
        wf = MultiAgentCodegenWorkflowAsync(SimpleNamespace(cfg=cfg, llm=llm))
        wf._started_at -= 2

        with self.assertRaisesRegex(TimeoutError, "wall-clock budget"):
            wf._check_resource_limits()


if __name__ == "__main__":
    unittest.main()
