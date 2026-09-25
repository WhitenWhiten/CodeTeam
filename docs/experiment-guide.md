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

## Independent official evaluation

Install the official tools in separate environments, with their dependencies:
CodeS at commit 0b624ab4ef22b0d9d223f274a986eb27fe090c88 and NL2RepoBench at
781a1da1ee41fb8edb0bed22f586d69111610edf. These are the inspected upstream revisions;
a different clean revision can be explicitly configured and is recorded. CodeS
uses its own calc_repobleu through validation/evaluation_scripts/batch_eval/get_metric.py,
not the unrelated PyPI CodeBLEU implementation. NL2Repo invokes its official
post_process_task and requires Docker and the upstream per-task images. The
generation machine does not need these tools. Transfer frozen artifacts and the
generation plan to an evaluator, adjusting deployment paths in a new protocol.

~~~json
{
  "evaluation_id": "official-v1",
  "experiment_dir": "runs/pilot-v1",
  "tasks": {
    "task-001": {
      "sketchbleu": {"checkout": "tools/CodeS", "reference": "private/reference/task-001", "python": "/path/to/metric-env/bin/python"},
      "nl2repo": {"checkout": "tools/NL2RepoBench", "project": "official-project-name", "python": "/path/to/benchmark-env/bin/python", "timeout_seconds": 1800}
    }
  }
}
~~~

Each task can request either or both evaluators. Run:

~~~text
codeteam-experiment evaluate evaluation.json
codeteam-experiment evaluate evaluation.json --resume
~~~

Evaluation uses a subprocess and a disposable repository copy. The official
NL2Repo harness removes packaging/test files before testing; that upstream
behavior is preserved and cannot modify the published generation artifact.
Original raw scores, subprocess logs, tool revisions, reference/metadata hashes,
artifact hashes and normalized results are retained. Scores are fractions [0,1].
NL2Repo uses the official task's total-test denominator, not just collected tests.
All-tests-pass additionally requires no failed/error tests and successful commands.
Pass@1 averages single-run success over seeds per task and then across tasks.
Infrastructure failures/timeouts remain missing evaluations and block a complete
aggregate; they are never silently omitted. Generation without an artifact is an
explicit zero-score generation failure. To retry an evaluator failure, use a new
evaluation_id so the original evidence survives.

Process separation enforces the pipeline boundary, not an OS security sandbox.
Run untrusted generated code on a dedicated evaluator host/container environment.
NL2Repo containers are removed on timeout/cancellation; build images and logs are
retained for audit. The default registry tags are inherited from the official
harness; the returned built-image ID is retained in official.json.

## Measured cost and random seeds

The manifest seed is applied to Architect preferences, ownership randomization and
the provider sampling seed. Standalone runs also accept --seed / CODETEAM_LLM_SEED.
The OpenAI-compatible endpoint must support the seed parameter: unsupported seeds
fail explicitly, rather than being silently discarded. Provider seed behavior is
best effort; requested seed, actual response model and system fingerprint are
recorded. Mock providers remain deterministic fixtures, not random-seed evidence.

Each model call records role, agent, stage, target file where relevant, messages,
response, input/output/total provider tokens, timestamps and latency. Attribution
uses task-local context and is unaffected by concurrent developers completing in
a different order. Unknown usage is retained as a separately marked conservative
budget estimate, never represented as measured input/output tokens.

~~~text
codeteam-experiment costs runs/pilot-v1
codeteam-experiment costs runs/pilot-v1 --input-usd-per-million 1 --output-usd-per-million 2
~~~

The optional prices are user-supplied examples, not current market prices. Dollar
estimates are null unless all calls have a complete token breakdown. GPU hours are
null for API inference without external hardware telemetry. Role model latency
is the sum of call durations and can overlap; it is not run wall-clock time.

Token, call and wall-clock ceilings survive checkpoint recovery. Time is persisted
at stages and every second. After an unclean process death the unclosed interval
is conservatively charged through restart (including possible downtime), with an
explicit conservative_recovery flag. Normal completed/cancelled invocations retain
measured active time. Interrupted planning restarted in a new retained attempt
carries forward the preceding attempt's resource charges. Terminal failed samples
are not retried by --resume.


## Executed mechanism variants

See [the runtime mechanism protocol](mechanism-runtime.md) for independent switches and evidence paths. Known labels such as no_cto, no_live_briefs, no_branches, no_qa and full_context require corresponding actual configuration. Custom labels require mechanism_expectations. plan.json records verified expectations and the effective mechanism manifest; runtime events establish what executed. Completely removing SDS needs a separate freeform adapter and is explicitly rejected here. A QA-disabled artifact is generated_unverified, never falsely marked QA-successful.
