import asyncio
from types import SimpleNamespace
import pytest
from app.config import SystemConfig
from app.bootstrap import bootstrap
from core.llm import LLMClient
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync


def test_failed_architect_does_not_discard_later_candidates(tmp_path):
    cfg=SystemConfig(workspace=str(tmp_path),architects=2,sds_retry=0)
    ctx=bootstrap(cfg)
    class Model(LLMClient):
        calls=0
        async def structured_json(self,prompt,schema=None):
            self.calls+=1
            if self.calls==1: raise ValueError("invalid candidate")
            return self._mock_sds()
    ctx.llm=Model(cfg.llm)
    wf=MultiAgentCodegenWorkflowAsync(ctx)
    candidates=asyncio.run(wf._collect_sds("requirements"))
    assert len(candidates)==1
    attempts=ctx.artifacts.read_json("planning/candidate_attempts.json")
    assert [r["status"] for r in attempts]==["rejected","accepted"]
