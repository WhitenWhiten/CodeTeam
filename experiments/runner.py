from __future__ import annotations
import asyncio
import time
from pathlib import Path
from app.config import SystemConfig
from app.bootstrap import bootstrap
from core.contracts import to_jsonable
from core.requirements_preprocessor import preprocess_requirements
from orchestrator.workflow_async import MultiAgentCodegenWorkflowAsync
from utils.run_artifacts import RunArtifacts
from experiments.common import digest, now, read_json, snapshot, verify_artifact, write_json
from experiments.protocol import make_plan

async def generate(job, attempt, resume=False):
    cfg = SystemConfig.model_validate(job['config'])
    cfg.workspace = str(attempt / 'workspace')
    cfg.artifacts_dir = str(attempt / 'runtime')
    if resume and (attempt / 'runtime/checkpoint.json').is_file():
        cfg.resume_from = cfg.artifacts_dir
    question = job['requirements']
    if cfg.preprocess_requirements:
        question = preprocess_requirements(question)
    ctx = bootstrap(cfg)
    try:
        return to_jsonable(await MultiAgentCodegenWorkflowAsync(ctx).run(question))
    finally:
        close = getattr(ctx.llm, 'close', None)
        if close:
            await close()

async def run_experiment(manifest, resume=False, generator=generate):
    plan = make_plan(manifest)
    root = Path(plan['root'])
    lease = RunArtifacts(str(root))
    lease.acquire()
    try:
        plan_path = root / 'plan.json'
        if plan_path.exists():
            if read_json(plan_path) != plan:
                raise ValueError('Experiment definition or code changed; use a new experiment_id')
            if not resume:
                raise ValueError('Experiment exists; use --resume')
        else:
            write_json(plan_path, plan)
        results = []
        for job in plan['jobs']:
            folder = root / 'runs' / job['run_id']
            final = folder / 'result.json'
            if final.exists():
                saved = read_json(final)
                if saved['job_sha256'] != digest(job):
                    raise ValueError('Run identity mismatch')
                if saved.get('artifact'):
                    verify_artifact(saved['artifact'])
                results.append(saved)
                continue
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder / 'job.json', job)
            attempts = sorted(folder.glob('attempt-*'))
            attempt = attempts[-1] if attempts else folder / 'attempt-0001'
            recovering = bool(attempts)
            if recovering and not (attempt / 'runtime/checkpoint.json').exists() and not (attempt / 'generation.json').exists():
                attempt = folder / f'attempt-{len(attempts) + 1:04d}'
                recovering = False
            attempt.mkdir(exist_ok=True)
            start = time.monotonic()
            started_at = now()
            outcome_path = attempt / 'generation.json'
            if outcome_path.exists():
                outcome = read_json(outcome_path)
            else:
                try:
                    outcome = await generator(job, attempt, recovering)
                except asyncio.CancelledError:
                    write_json(attempt / 'interruption.json', {'at': now(), 'status': 'cancelled'})
                    raise
                except Exception as exc:
                    outcome = {'status': 'error', 'reason': f'{type(exc).__name__}: {exc}', 'repo_root': None}
                write_json(outcome_path, outcome)
            artifact = snapshot(outcome['repo_root'], folder / 'artifact') if outcome.get('repo_root') else None
            saved = {'version': 1, 'run_id': job['run_id'], 'job_sha256': digest(job),
                     'identity': {k: job[k] for k in ('benchmark', 'task_id', 'difficulty', 'condition_id', 'method', 'variant', 'seed')},
                     'started_at': started_at, 'finished_at': now(), 'invocation_seconds': time.monotonic() - start,
                     'attempt': str(attempt), 'generation': outcome, 'artifact': artifact}
            write_json(final, saved)
            results.append(saved)
        write_json(root / 'results.json', results)
        return results
    finally:
        lease.release()
