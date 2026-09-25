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


def test_cto_scores_every_candidate_and_breaks_ties_by_assumptions():
    from core.planning_contracts import rank_candidates, CRITERIA
    model=LLMClient(SimpleNamespace(provider="mock"))
    candidates=[{"candidate_id":str(i),"source_index":i,"sds":model._mock_sds()} for i in range(2)]
    result={"evaluations":[{"candidate_id":str(i),"scores":{k:2 for k in CRITERIA},"rationale":"reason","assumptions":["extra"] if i==0 else []} for i in range(2)]}
    assert rank_candidates(result,candidates)[0]["candidate_id"]=="1"
    result["evaluations"].pop()
    with pytest.raises(ValueError,match="exactly once"): rank_candidates(result,candidates)
