import asyncio
import json
import subprocess
import sys
from pathlib import Path
import pytest
from experiments.common import snapshot, write_json
from experiments.evaluation import evaluate, normalized, run_official, summarize
from experiments.runner import run_experiment
from test_experiments import manifest

def commit_fixture(root):
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    for args in (['add', '.'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']):
        subprocess.run(['git', '-C', str(root), *args], check=True)
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()

def test_official_sketchbleu_cli_bridge(tmp_path):
    checkout = tmp_path / 'tool'
    script = checkout / 'validation/evaluation_scripts/batch_eval/get_metric.py'
    script.parent.mkdir(parents=True)
    script.write_text('import sys,json\nfrom pathlib import Path\na=sys.argv\nassert Path(a[a.index("--pred")+1]).is_dir()\nr={k:0.5 for k in ["codebleu","ngram_match_score","weighted_ngram_match_score","syntax_match_score","dataflow_match_score"]}\nPath(a[a.index("--metric_file")+1]).write_text(json.dumps(r)+"\\n")\n')
    revision = commit_fixture(checkout)
    source = tmp_path / 'source'; source.mkdir(); (source / 'a.py').write_text('a=1')
    artifact = snapshot(source, tmp_path / 'published')
    result = asyncio.run(run_official('sketchbleu', {'checkout': str(checkout), 'revision': revision,
        'python': sys.executable, 'timeout_seconds': 10, 'reference': str(source)}, artifact, tmp_path / 'evaluation'))
    assert result['metrics']['SketchBLEU'] == 0.5
    assert (Path(artifact['path']) / 'a.py').read_text() == 'a=1'

def test_upstream_denominator_and_invalid_outputs():
    raw = {'status': 'success', 'pytest_results': {'passed': 2, 'failed': 0, 'errors': 0, 'total': 4},
           'test_results': {'command_results': [{'exit_code': 0}]}}
    assert normalized('nl2repo', raw)['pass_rate'] == 0.5
    assert not normalized('nl2repo', raw)['all_tests_pass']
    raw['pytest_results']['passed'] = 4
    assert normalized('nl2repo', raw)['all_tests_pass']
    raw['test_results']['command_results'][0]['exit_code'] = 1
    assert not normalized('nl2repo', raw)['all_tests_pass']
    raw['pytest_results']['total'] = 0
    with pytest.raises(ValueError): normalized('nl2repo', raw)

def test_nl2repo_official_postprocessor_only_receives_copy(tmp_path):
    checkout = tmp_path / 'tool'; checkout.mkdir()
    (checkout / 'test_data_service.py').write_text('from types import SimpleNamespace\ntest_data_list=[]\ndef read_all_test_data():\n test_data_list.append(SimpleNamespace(proName="fixture"))\n')
    package = checkout / 'openhands'; package.mkdir(); (package / '__init__.py').write_text('')
    (package / 'post_processor.py').write_text('from pathlib import Path\ndef post_process_task(uid, workspace, task, logger):\n Path(workspace,"pyproject.toml").unlink()\n return {"status":"success","pytest_results":{"passed":1,"failed":1,"errors":0,"total":2},"test_results":{"command_results":[{"exit_code":1}]}}\n')
    revision = commit_fixture(checkout)
    source = tmp_path / 'source'; source.mkdir(); (source / 'pyproject.toml').write_text('[project]')
    artifact = snapshot(source, tmp_path / 'published')
    result = asyncio.run(run_official('nl2repo', {'checkout': str(checkout), 'revision': revision,
        'project': 'fixture', 'python': sys.executable, 'timeout_seconds': 10}, artifact, tmp_path / 'evaluation'))
    assert result['metrics']['pass_rate'] == 0.5
    assert (Path(artifact['path']) / 'pyproject.toml').exists()

def test_pass_at_one_is_seed_mean_and_errors_are_not_dropped():
    rows = [{'run_id': str(i), 'identity': {'benchmark': 'b', 'condition_id': 'c', 'task_id': 't'},
             'evaluators': {'nl2repo': {'status': 'evaluated', 'metrics': {'pass_rate': float(i == 0), 'all_tests_pass': i == 0}}}}
            for i in range(3)]
    assert summarize(rows)[0]['Pass@1'] == 1/3
    rows[2]['evaluators']['nl2repo']['metrics'] = None
    assert summarize(rows)[0]['Pass@1'] is None
    assert summarize(rows)[0]['missing_evaluations'] == 1

def test_separate_evaluation_reuses_same_artifact_and_preserves_failures(tmp_path):
    generation_manifest = manifest(tmp_path, seeds=[1, 2])
    async def generate(job, attempt, resume):
        return {'status': 'error', 'repo_root': None}
    results = asyncio.run(run_experiment(generation_manifest, generator=generate))
    reference = tmp_path / 'reference'; reference.mkdir(); (reference / 'x.py').write_text('x=1')
    config = {'evaluation_id': 'official-v1', 'experiment_dir': 'outputs/smoke', 'tasks': {'shop': {
        'sketchbleu': {'checkout': 'official', 'reference': 'reference'}}}}
    path = tmp_path / 'evaluate.json'; write_json(path, config)
    async def forbidden(*args): raise AssertionError('No generated artifact to evaluate')
    rows = asyncio.run(evaluate(path, evaluator=forbidden))
    assert len(rows) == len(results) == 2
    assert all(r['evaluators']['sketchbleu']['status'] == 'no_artifact' for r in rows)
    assert asyncio.run(evaluate(path, True, forbidden)) == rows
