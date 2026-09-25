# Framework implementation plan

Scope: CodeTeam runtime only. Experimental result data and analysis are excluded.
Each task is implemented, checked, and committed separately.

- [x] T1: Canonical SDS and message contracts; nested class serialization.
- [x] T2: One workflow engine and explicit lifecycle results.
- [x] T3: Developer context, source-preserving repair, interface changes.
- [x] T4: QA execution, structured diagnostics, timeout cleanup.
- [x] T5: Dependency-aware verification and repair closure.
- [x] T6: Model providers, cancellation, usage and budgets.
- [x] T7: Workspace and Git collaboration semantics.
- [x] T8: RAG contracts, cache validation and observable fallback.
- [x] T9: Configuration, durable run records and stage recovery.
- [ ] T10: Integrated acceptance tests, packaging and usage documentation.

## Checks

T1: Contract tests cover nested methods through prompt rendering, invalid paths,
duplicate owners, JSON serialization and same-file symbol references.

T2: Lifecycle checks cover shared entrypoints, structured failures, worker cleanup,
wall-clock interruption and cancellation propagation.

T3: Verified existing-source delivery, full interface metadata, same-owner symbol
dependencies, signature fidelity and rejection of destructive invalid output.
Repairs use complete-file replacements with bounded validation retries.

T4: Both adapters share structured JUnit parsing and Python module execution.
Checks exercise pass/fail, collection errors, zero tests and subprocess timeout.
Setup/environment failures are not routed as source-code defects.

T5: Batch tests run only when their declared source dependencies are ready.
Symbol aliases participate in scheduling; changed APIs invalidate completed
consumers. Real pytest integration covers final repair verification, zero repair
budget and detection of unchanged failing code.

T6: Native async provider requests are cancellable and timeout-bounded. Transient
errors alone are retried; schema repairs share the same accounting. Concurrent
requests reserve a conservative UTF-8 byte estimate plus output capacity; missing
usage and interrupted requests retain that charge. Tests cover cancellation,
concurrent admission, unknown usage, call limits and workflow budget propagation.
No live model service is called by these tests.

T7: Writes require both SDS membership and agent ownership. Canonical paths are
confined to the workspace; writes are atomic and initialization preserves files.
Serialized Git branches start from current main, integrate by fast-forward only,
and report staging/commit/integration failures. Tests exercise repeat agent turns,
cross-owner denial, traversal aliases and a full clean Git-backed workflow.

T8: Retrieval returns a stable design_hint contract with backend and fallback
metadata. Architect-only retrieval is the default and roles are explicit. Invalid
corpora fail clearly; vector caches validate content, dimensions and finite values.
Atomic cache publication and recorded query history support audit and recovery.

T9: Validated JSON configuration supports environment and CLI overrides. Run
directories have exclusive process locks, atomic checkpoints, stage events, model
request/response records, usage snapshots and persisted QA bundles. Recovery from
the selected-design boundary verifies every source hash, restores completed work
and pending repair context, and retains prior call/token charges. Wall time is a
per-invocation limit. Tests cover interrupted runs, source drift and CLI recovery.
