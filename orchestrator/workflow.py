"""Compatibility facade using the shared async workflow engine."""
import asyncio
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync

class MultiAgentCodegenWorkflow(MultiAgentCodegenWorkflowAsync):
    def run_sync(self, question):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(question))
        raise RuntimeError('Use await workflow.run() inside an event loop')
