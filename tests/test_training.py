import asyncio
import json
from pathlib import Path
import pytest
from experiments.common import read_json, write_json
from experiments.runner import run_experiment
from test_experiments import manifest
from training.export import export_runtime
from training.prepare import encode_sample, prepare, verify_prepared
from training.protocol import METHODS, Sample
from training.train import load_config


class FixtureTokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        text = ''.join(m['role'] + ':' + m['content'] + '\n' for m in messages)
        if add_generation_prompt: text += 'assistant:'
        return list(text.encode())

    def save_pretrained(self, path):
        Path(path).mkdir(); (Path(path) / 'fixture.json').write_text('{}')


def dataset_config(tmp_path, *, unequal=False):
    sources = {}
    for method in METHODS:
        rows = []
        for i in range(4):
            rows.append({'sample_id': f'{method}-{i}', 'repository_id': f'repository-{i}',
                'method': method, 'stage': 'fixture', 'teacher': 'local-test-teacher', 'accepted': True,
                'messages': [{'role': 'user', 'content': f'Build repository {i}'},
                             {'role': 'assistant', 'content': 'answer' + (' longer' if unequal and method == 'codes' else '')}]})
        path = tmp_path / f'{method}.jsonl'
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        sources[method] = path.name
    config = tmp_path / 'prepare.json'
    write_json(config, {'datasets': sources, 'output_dir': 'prepared', 'tokenizer': 'fixture',
        'max_sequence_length': 128, 'validation_fraction': 0.25})
    return config


def test_repository_split_and_exact_matching_are_auditable(tmp_path):
    path = dataset_config(tmp_path)
    report = prepare(path, FixtureTokenizer())
    assert report['matched'] and len(report['split']) == 4
    assert len({json.dumps(report['counts'][m], sort_keys=True) for m in METHODS}) == 1
    train = set(report['counts']['vanilla']['train']['repositories'])
    heldout = set(report['counts']['vanilla']['validation']['repositories'])
    assert train.isdisjoint(heldout) and len(train) == 3 and len(heldout) == 1
    verify_prepared(tmp_path / 'prepared')
    with (tmp_path / 'prepared/codeteam.train.jsonl').open('a') as handle: handle.write('changed')
    with pytest.raises(ValueError, match='changed'): verify_prepared(tmp_path / 'prepared')


def test_token_mismatch_blocks_training_without_padding_or_truncation(tmp_path):
    with pytest.raises(ValueError, match='Token volumes'):
        prepare(dataset_config(tmp_path, unequal=True), FixtureTokenizer())
    assert not (tmp_path / 'prepared/manifest.json').exists()
    assert not read_json(tmp_path / 'prepared/matching_report.json')['matched']


def test_prompt_mask_and_overlong_rejection(tmp_path):
    path = dataset_config(tmp_path)
    sample = Sample.model_validate(json.loads((tmp_path / 'vanilla.jsonl').read_text().splitlines()[0]))
    result = encode_sample(sample, FixtureTokenizer(), 128)
    assert result['labels'].count(-100) > 0
    assert result['supervised_tokens'] == len('answer\n')
    with pytest.raises(ValueError, match='sequence_too_long'): encode_sample(sample, FixtureTokenizer(), 8)


def test_exclusions_apply_before_shared_repository_split(tmp_path):
    path = dataset_config(tmp_path)
    cfg = read_json(path); cfg['exclude_repositories'] = ['repository-0']; write_json(path, cfg)
    report = prepare(path, FixtureTokenizer())
    assert 'repository-0' not in report['split']
    assert report['rejected']['contamination_exclusion'] == 3


def test_export_rejects_mock_training_targets(tmp_path):
    path = manifest(tmp_path, seeds=[1])
    asyncio.run(run_experiment(path))
    repositories = tmp_path / 'repositories.json'; write_json(repositories, {'shop': 'source/shop'})
    result = export_runtime(tmp_path / 'outputs/smoke', repositories, tmp_path / 'samples.jsonl')
    assert result['accepted'] == 0 and result['rejected']
    assert all(r['reason'] == 'mock_error_or_missing_target' for r in result['rejected'])


def test_remote_training_requires_immutable_revision(tmp_path):
    path = tmp_path / 'train.json'
    write_json(path, {'prepared_dir': 'prepared', 'output_dir': 'models', 'model': 'remote/model', 'model_revision': 'main'})
    with pytest.raises(ValueError, match='immutable'): load_config(path)


def test_export_checks_final_source_and_preserves_role_provenance(tmp_path):
    path = manifest(tmp_path, seeds=[1])
    generated = asyncio.run(run_experiment(path))[0]
    runtime = Path(generated['attempt']) / 'runtime'
    # Synthetic test records exercise acceptance, not real teacher output.
    for file in runtime.glob('model_calls/*.json'):
        record = read_json(file); record['provider'] = 'fixture-real-api'
        write_json(file, record)
    repositories = tmp_path / 'repositories.json'; write_json(repositories, {'shop': 'source/shop'})
    output = tmp_path / 'accepted.jsonl'
    audit = export_runtime(tmp_path / 'outputs/smoke', repositories, output)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert audit['accepted'] > 0
    assert {r['stage'] for r in rows} >= {'planning', 'implementation'}
    assert all(r['repository_id'] == 'source/shop' and r['evidence']['artifact_sha256'] == generated['artifact']['sha256'] for r in rows)
