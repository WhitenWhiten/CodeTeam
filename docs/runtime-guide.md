# CodeTeam runtime guide

This guide describes the executable framework in version 0.2.0. Experimental
spreadsheets and their analysis are separate from these framework updates.

## Install and run

Python 3.11 or newer is required. From the replication-package directory:

~~~console
python -m pip install -e .
python -m app.main --config config.example.json
codeteam --provider mock --no-git --architects 1 --workspace ./workspace
~~~

The default provider is a deterministic mock for an online-shop example. It
exercises orchestration, file generation and real pytest execution; it does not
implement arbitrary user requirements. For real generation, set llm.provider to
openai, choose a model supported by your endpoint, and provide OPENAI_API_KEY in
the environment. llm.base_url is optional; there is no implicit third-party proxy.
Compatible endpoints must support the chat completion and JSON-object response
format used by this provider.

~~~console
codeteam --config my-config.json --requirements-file README-requirements.md
codeteam --question "Build a small Python library" --provider openai --model YOUR_MODEL
~~~

The CLI writes one JSON result to stdout, progress to stderr, and exits with 0
only after successful final validation. Exit 1 means a run with failed validation,
exhausted budget or runtime error; exit 2 means invalid configuration or startup
failure. An interactive interruption exits 130 and cancels active work.
The app.main_async module uses the same CLI and workflow engine. Python callers
can await MultiAgentCodegenWorkflowAsync(ctx).run(question), or use
MultiAgentCodegenWorkflow(ctx).run_sync(question) outside an event loop. Both
return RunResult, with status, stage, reason, repository, final QA and usage.

## Configuration and resource limits

Precedence is defaults < JSON file < environment < explicit CLI arguments.
The --config option and CODETEAM_CONFIG select a JSON file. Unknown JSON keys,
invalid numbers and invalid RAG settings are rejected. ENV_PATHS in app/config.py
contains the complete environment mapping. Common fields are:

| Configuration | Environment | Meaning |
|---|---|---|
| architects | CODETEAM_ARCHITECTS | Number of candidate designs |
| max_rounds | CODETEAM_MAX_QA_ROUNDS | Repair attempts, not test executions |
| max_token_budget | CODETEAM_MAX_TOKEN_BUDGET | Run token-accounting ceiling |
| max_model_calls | CODETEAM_MAX_MODEL_CALLS | Requests, including retries and JSON repairs |
| max_wall_clock_seconds | CODETEAM_MAX_WALL_CLOCK_SECONDS | Wall time per invocation |
| llm.request_timeout | CODETEAM_LLM_REQUEST_TIMEOUT | Timeout per model request |
| llm.request_retries | CODETEAM_LLM_REQUEST_RETRIES | Extra attempts for transient errors |
| test_timeout | CODETEAM_TEST_TIMEOUT | Timeout per setup/test process |
| python_executable | CODETEAM_PYTHON_EXECUTABLE | Python environment for setup and pytest |
| git.enabled | CODETEAM_GIT_COLLAB_ENABLED | Branch/commit integration |
| rag.enabled | CODETEAM_RAG_ENABLED | Design-reference retrieval |

Concurrent requests reserve UTF-8 byte-based input estimates plus allowed output
capacity. Provider-reported tokens reconcile these reservations. Missing usage,
failed requests and interrupted requests retain conservative reservation charges.
This is explicit admission accounting, not a model-specific tokenizer or a billing
guarantee. The mock uses conservative charges. A provider reporting more tokens
than admitted stops further work; already incurred usage cannot be undone.

## Execution contracts

- SDS validation checks file paths, ownership, nested class/method contracts,
  declared dependency references and cycles before generation. Only Python and
  pytest are executed. Fixed allocation updates owners consistently and omits
  empty workers when there are fewer files than configured workers.
- Developers receive the complete current target file, all declared dependency
  briefs and structured failure details. Python output is parsed before writing;
  missing declared functions/classes/methods and invalid syntax are rejected.
  This checks syntax and named interface presence, not full semantic correctness.
- Scheduling resolves file and symbol dependencies. Ready QA subsets verify
  completed dependencies. Public-interface changes invalidate completed consumers.
  Full tests run after repairs, including the last permitted repair. Repeated
  failures with unchanged source stop with an explicit no-progress reason.
- Both SDS membership and developer ownership are required for writes. Writes are
  atomic, paths are confined to the generated repository and initialization does
  not erase existing source. Shared-worktree Git operations are serialized. Agent
  branches start from current main and fast-forward back; conflicts and failures
  are surfaced. Disabling Git retains in-memory briefs and update reasons.
- Pytest runs through the configured interpreter and produces structured JUnit
  results. Collection, setup, environment and timeout failures remain distinct.
  Zero tests and skipped-only suites do not pass. There is no substitute runner
  when pytest is missing. QA tests are staged temporarily and removed after each
  execution; their full contents remain in run artifacts.

Generated code, tests and permitted setup commands run in the selected Python
environment. Process timeouts and path checks are not an operating-system sandbox.
Use a dedicated environment or container when isolation is required. Install pytest
and project dependencies there; auto-loaded host pytest plugins are disabled,
while explicitly requested plugins remain possible.

## Retrieval

Install the optional stack with python -m pip install -e ".[rag]". Configure an
explicit corpus path for installed packages; the research corpus is not shipped
in the wheel. Use rag.index_backend=lexical for dependency-light tests. Vector mode
uses the configured sentence-transformers model and FAISS HNSW.

rag.roles defaults to ["architect"]; cto is opt-in. Both backends return design_hint
results with source, chunk, score and actual backend metadata. fallback_mode=error
rejects vector failures; lexical records the reason when falling back during index
construction or a query. Empty or invalid corpora fail explicitly. Cached vectors
are keyed by corpus/model/chunk settings and checked for checksum, shape, finite
values and nonzero vectors before reuse.

## Run records and recovery

Each run has a unique artifact directory under workspace/run_artifacts/ unless
artifacts_dir is explicit. An OS-released exclusive lock prevents concurrent
processes from writing the same run. Important files include:

- effective_config.json: resolved configuration; API keys are not copied from the environment.
- events.jsonl: stages, model request completion and final status.
- model_calls/*.json: prompts, outputs, parameters, usage source, errors and elapsed time.
- model_usage.json: counters and reservations persisted before and after requests.
- planning/: selected SDS, candidate traces and retrieval history.
- qa/test_bundle.json and qa/round_*.json: test sources and structured results.
- checkpoint.json: chosen design, source hashes, completed files, pending fixes and briefs.
- repository/final.json: result of the latest accepted invocation.

Prompts and outputs may contain requirement/source content; artifacts are local
run records. Do not put API credentials in requirements, prompts or endpoint URLs.

~~~console
codeteam --resume ./workspace/run_artifacts/run-... --max-calls 150 --max-tokens 1500000
~~~

Resume begins at the selected-design boundary: it reuses the SDS and QA bundle,
checks every source hash, and restores the scheduler and dependency briefs.
Completed files are not regenerated. Pending repair issues are restored. Final
validation still runs even when all generation was previously completed.

Requirements and model/RAG/Git/allocation identity must match. Externally modified
source, missing files or a dirty Git tree are rejected rather than overwritten.
Token/call costs carry forward; outstanding reservations after a crash are charged
conservatively. You may explicitly raise total resource/repair budgets. Wall time
starts again per invocation. Work before design selection can be inspected in
traces but has no resumable implementation checkpoint.

## Verification and boundaries

~~~console
python -m pytest -q
python scripts/check_install.py
~~~

Tests include real subprocess pytest runs, deterministic source repair, classes,
src layouts, fixed/dynamic ownership, Git integration, cancellation, usage limits,
RAG fallback/cache corruption and interrupted-run recovery. The installation
check builds a wheel without network, installs it temporarily and runs its console
entrypoint outside this checkout.

Provider tests use fake async clients, and vector-index tests use fake embeddings.
Live provider responses, model quality, downloaded embeddings and paper benchmark
accuracy are not established by this suite. Passing model-generated QA tests does
not establish performance on an independent upstream acceptance suite. SFT training
and benchmark-data reproduction are outside these framework updates.

The old roles.developer_agent.DeveloperAgent name aliases the async worker;
thread-based orchestration is retired. roles.qa_agent.QAAgent shares the active QA
implementation. Use the workflow facade for synchronous callers. The legacy
pytest_fallback, synchronous event bus and round manager are unused by the engine.
