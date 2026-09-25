"""Independent evaluation: this module is never imported by generation."""
from __future__ import annotations
import asyncio
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from app.config import ConfigModel
from experiments.common import digest, files_digest, now, read_json, snapshot, verify_artifact, write_json
from runtime_adapters.process import run_process
from utils.run_artifacts import RunArtifacts

CODES_REVISION = '0b624ab4ef22b0d9d223f274a986eb27fe090c88'
NL2REPO_REVISION = '781a1da1ee41fb8edb0bed22f586d69111610edf'

class OfficialTool(ConfigModel):
    checkout: str
    revision: str = Field(pattern=r'^[a-f0-9]{40}$')
    python: str = sys.executable
    timeout_seconds: float = Field(default=1800, gt=0)

class SketchBLEU(OfficialTool):
    revision: str = CODES_REVISION
    reference: str

class NL2Repo(OfficialTool):
    revision: str = NL2REPO_REVISION
    project: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')

class EvaluationTask(ConfigModel):
    sketchbleu: SketchBLEU | None = None
    nl2repo: NL2Repo | None = None

    @model_validator(mode='after')
    def has_metric(self):
        if self.sketchbleu is None and self.nl2repo is None:
            raise ValueError('At least one external evaluator is required')
        return self

class Evaluation(ConfigModel):
    version: Literal[1] = 1
    evaluation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    experiment_dir: str
    tasks: dict[str, EvaluationTask]

def official_checkout(path, revision):
    path = Path(path).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.STDOUT, text=True).strip()
    if git('rev-parse', 'HEAD') != revision:
        raise ValueError(f'Official evaluator revision mismatch: {path}')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError(f'Official evaluator has tracked modifications: {path}')
    return path

def normalized(kind, raw):
    if kind == 'sketchbleu':
        keys = {'SketchBLEU': 'codebleu', 'B': 'ngram_match_score', 'BW': 'weighted_ngram_match_score',
                'MS': 'syntax_match_score', 'MD': 'dataflow_match_score'}
        values = {out: raw[key] for out, key in keys.items()}
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
            raise ValueError('Invalid official SketchBLEU output')
        return values
    if raw.get('status') != 'success':
        raise RuntimeError(raw.get('error', 'Official NL2Repo post-processing failed'))
    counts = raw['pytest_results']
    for key in ('passed', 'failed', 'errors', 'total'):
        if type(counts[key]) is not int or counts[key] < 0:
            raise ValueError('Invalid upstream test counts')
    if counts['total'] <= 0 or counts['passed'] > counts['total']:
        raise ValueError('Invalid upstream test denominator or duplicate pass counts')
    commands = raw['test_results']['command_results']
    all_pass = (counts['passed'] == counts['total'] and not counts['failed'] and not counts['errors']
                and bool(commands) and all(c['exit_code'] == 0 for c in commands))
    return {'pass_rate': counts['passed'] / counts['total'], 'all_tests_pass': all_pass, 'counts': counts}

async def run_official(kind, config, artifact, output):
    checkout = official_checkout(config['checkout'], config['revision'])
    output.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name('evaluation_worker.py').resolve()
    # The official NL2Repo postprocessor removes packaging/test files. Only a
    # disposable copy is handed over; scoring never mutates the generated artifact.
    working = snapshot(artifact['path'], output / 'workspace')
    request = {'kind': kind, 'config': config, 'workspace': working['path'],
               'output': str(output / 'official.json'), 'task_uuid': 'ct-' + digest(str(output))[:20]}
    write_json(output / 'request.json', request)
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = str(checkout / 'validation/evaluation_scripts/codebleu') if kind == 'sketchbleu' else str(checkout)
    try:
        process = await run_process([config['python'], str(worker), str(output / 'request.json')], checkout, config['timeout_seconds'], env)
    finally:
        # A killed official harness can otherwise leave its detached container.
        if kind == 'nl2repo':
            try:
                await run_process(['docker', 'rm', '-f', 'python-test-' + request['task_uuid']], output, 30)
            except OSError:
                pass
    write_json(output / 'process.json', process)
    if process['timed_out']:
        return {'status': 'timeout', 'metrics': None}
    if process['returncode'] != 0 or not (output / 'official.json').exists():
        return {'status': 'environment_error', 'metrics': None, 'reason': process['output'][-4000:]}
    raw = read_json(output / 'official.json')
    return {'status': 'evaluated', 'metrics': normalized(kind, raw), 'raw_file': str(output / 'official.json')}

async def evaluate(manifest, resume=False, evaluator=run_official):
    manifest = Path(manifest).resolve()
    spec = Evaluation.model_validate(read_json(manifest))
    experiment = (manifest.parent / spec.experiment_dir).resolve()
    plan = read_json(experiment / 'plan.json')
    if set(spec.tasks) != {j['task_id'] for j in plan['jobs']}:
        raise ValueError('Evaluation tasks must exactly cover the generation plan')
    resolved = spec.model_dump()
    for task in resolved['tasks'].values():
        for kind, config in task.items():
            if config is None:
                continue
            config['checkout'] = str((manifest.parent / config['checkout']).resolve())
            if kind == 'sketchbleu':
                config['reference'] = str((manifest.parent / config['reference']).resolve())
                config['reference_sha256'] = digest(files_digest(config['reference']))
            else:
                config['task_metadata_sha256'] = digest(files_digest(Path(config['checkout']) / 'test_files' / config['project']))
    identity = {'config': resolved, 'generation_plan_sha256': digest(plan),
                'adapter_sha256': digest({p.name: p.read_text(encoding='utf-8') for p in (Path(__file__), Path(__file__).with_name('evaluation_worker.py'))})}
    root = experiment / 'evaluations' / spec.evaluation_id
    lock = RunArtifacts(str(root)); lock.acquire()
    try:
        if (root / 'protocol.json').exists():
            if read_json(root / 'protocol.json') != identity:
                raise ValueError('Evaluation protocol changed; choose a new evaluation_id')
            if not resume:
                raise ValueError('Evaluation exists; use --resume')
        else:
            write_json(root / 'protocol.json', identity)
        rows = []
        for job in plan['jobs']:
            generation = read_json(experiment / 'runs' / job['run_id'] / 'result.json')
            if generation['job_sha256'] != digest(job):
                raise ValueError('Generation result does not match the planned job')
            artifact = generation['artifact']
            if artifact:
                verify_artifact(artifact)
            out = root / job['run_id']
            result_path = out / 'result.json'
            if result_path.exists():
                saved = read_json(result_path)
                if saved['generation_sha256'] != digest(generation):
                    raise ValueError('Generation record changed after evaluation')
                rows.append(saved)
                continue
            row = {'run_id': job['run_id'], 'identity': generation['identity'], 'generation_status': generation['generation']['status'],
                   'generation_sha256': digest(generation), 'artifact_sha256': artifact['sha256'] if artifact else None,
                   'evaluators': {}, 'evaluated_at': now()}
            for kind, config in resolved['tasks'][job['task_id']].items():
                if config is None:
                    continue
                if artifact is None:
                    value = {'status': 'no_artifact', 'metrics': {'pass_rate': 0.0, 'all_tests_pass': False} if kind == 'nl2repo' else {'SketchBLEU': 0.0}}
                else:
                    try:
                        previous = list((out / kind).glob('attempt-*'))
                        value = await evaluator(kind, config, artifact, out / kind / f'attempt-{len(previous) + 1:04d}')
                    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
                        value = {'status': 'evaluation_error', 'metrics': None, 'reason': f'{type(exc).__name__}: {exc}'}
                    verify_artifact(artifact)
                row['evaluators'][kind] = value
            write_json(result_path, row)
            rows.append(row)
        write_json(root / 'results.json', rows)
        write_json(root / 'summary.json', summarize(rows))
        return rows
    finally:
        lock.release()

def summarize(rows):
    """Task-first seed means; incomplete external evaluation never looks complete."""
    groups = {}
    seen = set()
    for row in rows:
        if row['run_id'] in seen:
            raise ValueError('Duplicate evaluated run')
        seen.add(row['run_id'])
        identity = row['identity']
        for kind, value in row['evaluators'].items():
            key = (identity['benchmark'], identity['condition_id'], kind)
            groups.setdefault(key, []).append((identity['task_id'], value))
    summaries = []
    for (benchmark, condition, kind), entries in groups.items():
        metric = 'SketchBLEU' if kind == 'sketchbleu' else 'pass_rate'
        tasks, successes = {}, {}
        missing = 0
        for task, value in entries:
            if value['metrics'] is None:
                missing += 1
                continue
            tasks.setdefault(task, []).append(value['metrics'][metric])
            if kind == 'nl2repo':
                successes.setdefault(task, []).append(float(value['metrics']['all_tests_pass']))
        average = lambda x: sum(sum(v) / len(v) for v in x.values()) / len(x) if x else None
        summaries.append({'benchmark': benchmark, 'condition_id': condition, 'evaluator': kind,
                          'runs': len(entries), 'missing_evaluations': missing, 'complete': missing == 0,
                          metric: average(tasks) if not missing else None,
                          'Pass@1': average(successes) if kind == 'nl2repo' and not missing else None})
    return summaries
