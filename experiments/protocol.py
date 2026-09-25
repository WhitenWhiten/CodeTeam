from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from app.config import ConfigModel, SystemConfig
from experiments.common import digest, files_digest, read_json

class Task(ConfigModel):
    task_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    requirements_file: str
    difficulty: Literal['easy', 'medium', 'hard', 'unspecified'] = 'unspecified'

class Condition(ConfigModel):
    condition_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    method: Literal['codeteam'] = 'codeteam'
    variant: str = 'full'
    config: SystemConfig = Field(default_factory=SystemConfig)

    @model_validator(mode='after')
    def controlled_paths(self):
        if self.config.requirements_file or self.config.resume_from or self.config.artifacts_dir:
            raise ValueError('Experiment runner controls requirements, resume and artifact paths')
        return self

class Experiment(ConfigModel):
    version: Literal[1] = 1
    experiment_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    benchmark: str
    output_dir: str
    tasks: list[Task] = Field(min_length=1)
    conditions: list[Condition] = Field(min_length=1)
    seeds: list[int] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_axes(self):
        for values in ([t.task_id for t in self.tasks], [c.condition_id for c in self.conditions], self.seeds):
            if len(values) != len(set(values)):
                raise ValueError('Duplicate experiment axis value')
        return self

def code_identity():
    root = Path(__file__).resolve().parents[1]
    sources = {}
    for folder in ('app', 'actions', 'core', 'orchestrator', 'roles', 'runtime_adapters', 'utils', 'rag', 'prompts', 'experiments', 'training'):
        if (root / folder).is_dir():
            sources.update({f'{folder}/{p}': h for p, h in files_digest(root / folder).items() if p.endswith(('.py', '.md'))})
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {'git_commit': commit, 'source_sha256': digest(sources)}

def make_plan(manifest):
    manifest = Path(manifest).resolve()
    spec = Experiment.model_validate(read_json(manifest))
    root = (manifest.parent / spec.output_dir / spec.experiment_id).resolve()
    jobs = []
    identity = code_identity()
    for task in spec.tasks:
        question = (manifest.parent / task.requirements_file).read_text(encoding='utf-8-sig')
        if not question.strip():
            raise ValueError(f'Empty requirements: {task.task_id}')
        for condition in spec.conditions:
            for seed in spec.seeds:
                cfg = condition.config.model_dump()
                cfg.update(architect_seed=seed, workspace='.', artifacts_enabled=True, resume_from=None, artifacts_dir=None)
                cfg['developer_allocation']['assignment_seed'] = seed
                if 'seed' in cfg['llm']:
                    cfg['llm']['seed'] = seed
                for field in ('corpus_file', 'index_dir'):
                    if cfg['rag'].get(field):
                        cfg['rag'][field] = str((manifest.parent / cfg['rag'][field]).resolve())
                job = {'benchmark': spec.benchmark, 'task_id': task.task_id, 'difficulty': task.difficulty,
                       'condition_id': condition.condition_id, 'method': condition.method, 'variant': condition.variant,
                       'seed': seed, 'requirements': question, 'requirements_sha256': digest(question), 'config': cfg}
                job['run_id'] = digest(job)[:24]
                jobs.append(job)
    return {'version': 1, 'experiment_id': spec.experiment_id, 'root': str(root), 'code': identity, 'jobs': jobs}
