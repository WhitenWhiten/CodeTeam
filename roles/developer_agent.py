"""Compatibility import; use the async worker or Workflow.run_sync for sync callers."""
from roles.developer_worker_async import DeveloperWorkerAsync

DeveloperAgent = DeveloperWorkerAsync
