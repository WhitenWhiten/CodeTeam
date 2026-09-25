# Framework implementation plan

Scope: CodeTeam runtime only. Experimental result data and analysis are excluded.
Each task is implemented, checked, and committed separately.

- [x] T1: Canonical SDS and message contracts; nested class serialization.
- [x] T2: One workflow engine and explicit lifecycle results.
- [x] T3: Developer context, source-preserving repair, interface changes.
- [x] T4: QA execution, structured diagnostics, timeout cleanup.
- [x] T5: Dependency-aware verification and repair closure.
- [ ] T6: Model providers, cancellation, usage and budgets.
- [ ] T7: Workspace and Git collaboration semantics.
- [ ] T8: RAG contracts, cache validation and observable fallback.
- [ ] T9: Configuration, durable run records and stage recovery.
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
