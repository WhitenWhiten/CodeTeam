# Experiment and evaluation framework

Generation manifests contain public requirements only. Private reference code,
upstream tests and scoring configuration belong to a separate evaluation manifest.
The current generation adapter is CodeTeam; other baseline adapters are a separate
work item, not aliases for this implementation.

Create a JSON manifest with an experiment_id, benchmark, output_dir, tasks
(task_id, requirements_file, difficulty), conditions (condition_id, method=codeteam,
variant, config using the normal SystemConfig), and seeds. Paths resolve relative
to the manifest. Each task x condition x seed is a separate run. The runner does
not read CODETEAM_* environment configuration; credentials remain in the provider
environment. No private evaluation paths are accepted in task definitions.

~~~json
{
  "experiment_id": "pilot-v1",
  "benchmark": "your-benchmark",
  "output_dir": "./runs",
  "tasks": [{"task_id": "task-001", "requirements_file": "requirements.md", "difficulty": "easy"}],
  "conditions": [{"condition_id": "full", "method": "codeteam", "variant": "full",
    "config": {"llm": {"provider": "mock"}, "git": {"enabled": false}}}],
  "seeds": [11, 22, 33]
}
~~~

~~~text
codeteam-experiment plan experiment.json
codeteam-experiment run experiment.json
codeteam-experiment run experiment.json --resume
~~~

plan.json records full effective configurations, public requirement text, stable
run identifiers and source-code provenance. Each run retains its runtime records,
generation status and a checksum-verified repository snapshot. Failed and truncated
runs are retained. Resume skips all terminal outcomes, including failures; it does
not quietly retry a failed sample to improve scores. Interrupted generation resumes
from a checkpoint, or starts a new retained attempt if planning was interrupted.
Changing code/configuration/requirements requires a new experiment identity.

The package tests use mock providers and fixture tasks. They establish the
execution contract, not benchmark scores or real-model quality.
