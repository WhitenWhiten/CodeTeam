import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace as NS
from app.bootstrap import bootstrap
from core.call_context import model_call_context
from core.llm_openai import OpenAILLM
from core.model_usage import UsageLedger
from core.contracts import RunStatus
from experiments.common import write_json
from experiments.costs import cost_report
from experiments.runner import run_experiment
from orchestrator.workflow import MultiAgentCodegenWorkflow
from test_config_recovery import interrupted_run
from test_experiments import manifest

def test_concurrent_call_roles_and_provider_seed_are_preserved():
    requests = []
    async def create(**kwargs):
        requests.append(kwargs)
        await asyncio.sleep(0.001)
        return NS(choices=[NS(message=NS(content='ok'))], usage={'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5},
                  id='response', model='served-model', system_fingerprint='fingerprint')
    model = OpenAILLM(client=NS(chat=NS(completions=NS(create=create))), seed=23)
    async def call(role):
        with model_call_context(role=role, stage='implementation'):
            return await model.text(role)
    async def run():
        await asyncio.gather(call('Developer'), call('QA'))
    asyncio.run(run())
    assert {r['role'] for r in model.usage.records} == {'Developer', 'QA'}
    assert all(r['seed'] == 23 for r in requests)
    assert model.usage.snapshot()['input_tokens'] == 6
    assert model.usage.snapshot()['output_tokens'] == 4
    assert model.usage.snapshot()['reported_tokens'] == 10
    assert model.usage.snapshot()['estimated_tokens'] == 0
    assert all(r['system_fingerprint'] == 'fingerprint' for r in model.usage.records)

def test_crash_reservations_are_estimates_after_restore():
    ledger = UsageLedger()
    ledger.reserve('interrupted', 10)
    restored = UsageLedger(); restored.restore(ledger.snapshot())
    saved = restored.snapshot()
    assert saved['estimated_tokens'] == saved['total_tokens'] > 0
    assert saved['unknown_usage_calls'] == 1 and saved['pending_calls'] == 0

def test_resume_cannot_reset_wall_time_budget(tmp_path):
    cfg, first, _ = interrupted_run(tmp_path)
    timing = Path(cfg.artifacts_dir) / 'time_usage.json'
    write_json(timing, {'elapsed_seconds': 10, 'recorded_at_unix': time.time(), 'closed': True})
    cfg.resume_from = cfg.artifacts_dir
    cfg.max_model_calls = 20
    cfg.max_wall_clock_seconds = 5
    result = MultiAgentCodegenWorkflow(bootstrap(cfg)).run_sync(cfg.user_question)
    assert result.status == RunStatus.BUDGET_EXHAUSTED
    assert result.usage['calls'] == first.usage['calls']
    assert result.timing['elapsed_seconds'] >= 10

def test_unknown_usage_does_not_create_fake_dollar_cost(tmp_path):
    path = manifest(tmp_path, seeds=[17])
    result = asyncio.run(run_experiment(path))[0]
    rows = cost_report(tmp_path / 'outputs/smoke', 1.0, 2.0)
    assert rows[0]['monetary_equivalent_usd'] is None
    assert rows[0]['input_tokens'] is None
    assert set(rows[0]['roles']) == {'Architect', 'CTO', 'Developer', 'QA'}
    assert rows[0]['usage']['estimated_tokens'] > 0
    assert rows[0]['remaining_files'] == []
    records = [json.loads(p.read_text()) for p in Path(result['attempt']).glob('runtime/model_calls/*.json')]
    assert all(r['sampling_seed'] == 17 for r in records)
