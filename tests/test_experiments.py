import asyncio
import json
from pathlib import Path
import pytest
from experiments.protocol import make_plan
from experiments.runner import run_experiment
from experiments.common import write_json

def manifest(tmp_path, **overrides):
    (tmp_path / 'requirements.md').write_text('Build a shop', encoding='utf-8')
    value = {'experiment_id': 'smoke', 'benchmark': 'fixture', 'output_dir': 'outputs',
             'tasks': [{'task_id': 'shop', 'requirements_file': 'requirements.md'}],
             'conditions': [{'condition_id': 'full', 'config': {'architects': 1, 'git': {'enabled': False}}}], 'seeds': [11, 22]}
    value.update(overrides)
    path = tmp_path / 'experiment.json'
    write_json(path, value)
    return path

def test_matrix_identity_and_hidden_inputs_rejected(tmp_path):
    path = manifest(tmp_path)
    plan = make_plan(path)
    assert len(plan['jobs']) == 2 and len({j['run_id'] for j in plan['jobs']}) == 2
    assert plan == make_plan(path)
    raw = json.loads(path.read_text())
    raw['tasks'][0]['upstream_tests'] = 'hidden'
    write_json(path, raw)
    with pytest.raises(ValueError):
        make_plan(path)

def test_batch_retains_failures_and_resume_checks_artifact(tmp_path):
    path = manifest(tmp_path)
    calls = []
    async def generator(job, attempt, resume):
        calls.append(job['seed'])
        repo = attempt / 'repo'; repo.mkdir()
        (repo / 'answer.py').write_text('answer = 42')
        return {'status': 'budget_exhausted', 'repo_root': str(repo)}
    results = asyncio.run(run_experiment(path, generator=generator))
    assert len(results) == 2 and len(calls) == 2
    assert all(r['artifact'] and r['generation']['status'] == 'budget_exhausted' for r in results)
    assert asyncio.run(run_experiment(path, True, generator)) == results
    assert len(calls) == 2
    (Path(results[0]['artifact']['path']) / 'answer.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(run_experiment(path, True, generator))

def test_changed_definition_cannot_reuse_results(tmp_path):
    path = manifest(tmp_path)
    async def failing(*args):
        raise RuntimeError('provider failed')
    results = asyncio.run(run_experiment(path, generator=failing))
    assert len(results) == 2 and results[0]['generation']['status'] == 'error'
    (tmp_path / 'requirements.md').write_text('Different task')
    with pytest.raises(ValueError, match='definition'):
        asyncio.run(run_experiment(path, True, failing))

def test_runtime_adapter_executes_mock_and_freezes_repository(tmp_path):
    path = manifest(tmp_path, seeds=[1])
    result = asyncio.run(run_experiment(path))[0]
    assert result['generation']['status'] == 'success', result
    assert 'shop/catalog.py' in result['artifact']['files']
