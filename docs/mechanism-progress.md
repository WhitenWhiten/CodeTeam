# Mechanism implementation progress

Baseline: 2d9a4cb. Started 2026-09-25. Scope: M01-M16 in mechanism-audit-2026-09-25.md.
Each mechanism is committed separately. Acceptance runs are batched; a checked item means implemented, with validation results recorded below. Existing data/analysis changes are excluded.

- [x] M01: SDS semantics
- [x] M02: Implementation contracts
- [x] M03: Delivery completeness
- [x] M04: Candidate rejection
- [x] M05: CTO ranking
- [x] M06: Progressive QA
- [x] M07: Evidence-based routing
- [x] M08: Minimal invalidation
- [x] M09: Durable interface communication
- [x] M10: Bounded context and briefing
- [x] M11: Planning diversity
- [x] M12: Closed resource state
- [x] M13: Workload-aware allocation
- [x] M14: Retrieval information contracts
- [x] M15: Requirement traceability
- [x] M16: Mechanism controls and acceptance

## Batch validation

Batch A and B passed; Batch C regression fixed and focused recheck passed. Final integration acceptance is recorded at the end of this file.

M01: Added versioned semantic validation, alias conflict rejection, unambiguous dependency resolution and syntactic declaration checks. Batch A acceptance pending.

M02: Implemented AST signature/default/annotation checks before writes, static internal import checks, and explicit unresolved dynamic import reports. Batch A pending.

M03: Added explicit static/QA producers, dependency-manifest requirement, required-file delivery gate and removal of temporary test placeholders. Batch A running.
Batch A: 29 passed. Strict-contract fixtures now declare required annotations/manifests; delivered temporary QA paths have explicit absent checkpoint entries.

M04: Candidate-local rejection now continues remaining Architects and persists every attempt, parsed/normalized payload and raw provider JSON-repair trace. Minimum valid pool is explicit. Batch B pending.

M05: CTO now scores every stable candidate ID; code ranks by total, assumptions and graph fan-out with deterministic ties. Invalid decisions retry explicitly; ranked fallback is recorded. Batch B pending.

M06: QA receives original requirements and accepted source/interface snapshots, generates per changed batch, retains regression files and fixtures, records test versions, and bounds syntax/import repairs without silently weakening assertions. Batch B pending.

M07: Unified canonical dependency resolution, source-backed syntax/API diagnostics, unknown ambiguous providers and lossless multi-failure routing. Batch B pending.

M08: Separated retest hints from regeneration; versioned public signatures, bindings, attributes/imports and merged multi-upstream invalidations. Private helpers/docs do not invalidate consumers. Batch B pending.

Batch B: 36 passed (planning, progressive QA, evidence routing, minimal invalidation, scheduler, repair and framework integration).

M09: Persisted replayable publish/consume journal, commit/source/API/parent identities and pre-write stale-dependency rejection with bounded recollection. Shared-worktree writes remain serialized. Batch C pending.

M10: Added deterministic UTF-8 context caps, omission receipts and complete-target-or-fail policy; up to two explicit interface-only requests; SDS-sourced invariants reach prompts and published briefs. Batch C pending.

M11: Recorded file/API/module similarities and rename-independent topology summaries; explicit keep/reject/bounded-retry policy handles duplicates. Generic src/tests directories do not establish diversity. Default keeps and reports duplicates. Batch C pending.

M12: Durable counters now distinguish planning, generation retries, briefing, QA tests and interface requeues; per-file caps stop drift, resume preserves state, failed/budget-stopped outputs list pending and unverified files. Uncapped QA requires a global ceiling. Batch C pending.

Batch C: 26 passed; one regression exposed an unsafe source field in the public summary allowlist. Renamed provenance to origin and removed source from the allowlist; focused recheck follows.

M13: Added explicit Architect or structural-heuristic effort estimates, reproducible owner/dependency/load reports and concurrent slot queueing that preserves ownership. Retained the documented small-batch QA barrier. Final batch pending.

M14: Typed source availability distinguishes raw README from provided summaries; one exact packet renderer records order/truncation/hash and both prompt boundaries. Frozen packet replay bypasses corpus/embeddings and validates query identity and budget. Final batch pending.

M15: Centralized original-to-normalized requirements at workflow entry; preserved API/config fences, removed noisy subtrees, and recorded stable IDs/source spans/filter decisions. File/test references and explicit unmapped coverage reach saved artifacts. Final batch pending.

M16: Completed independent runtime controls, validated experiment expectations, effective manifests, task/commit/QA evidence and integration acceptance. Integration also closed stale input, resumed QA, fixture readiness, literal defaults and dependency-manifest edge cases found in batch checks.

Final integration first pass: 146 passed, 8 failed. Updated legacy CTO/example-preservation expectations, supplied complete lifecycle fixtures, corrected a test condition ID, and restored pending QA verification before further generation on resume. Affected-range recheck: 32 passed.


## Final acceptance — 2026-09-25

- Consolidated framework suite: **158 passed in 53.29s**. Command: python -m pytest -q -p no:cacheprovider tests --ignore=tests/test_training_integration.py.
- Subsequent focused acceptance after the final manifest-parser patch and four added negative cases: **24 passed in 8.34s**, covering mechanism contracts/controls/journal, SDS contracts and the complete QA repair loop. This overlaps the consolidated suite and is not an additive count of distinct tests.
- New negative cases distinguish actual dependency declarations from comments/project names/build dependencies, follow planned requirements includes and reject cycles, reject stale dependency context before writing, and prevent a failed commit from publishing an accepted brief.
- Offline wheel build passed with --no-deps --no-build-isolation --no-index. New mechanism modules and prompt resources are present; the packaging dependency is declared. codeteam and codeteam-experiment CLI help checks passed.
- git diff --check passed. Existing data/analyze_experiment_results.py changes were neither modified nor staged.
- Optional training integration was excluded because this task changes runtime mechanisms, not training. No remote model calls, benchmark scoring, training or performance conclusions are part of this acceptance.
- All M01–M16 implementation items are complete. Shared-worktree serialization, Python/pytest scope, syntactic contracts and unsupported freeform no-SDS adapters remain explicit boundaries in mechanism-runtime.md.

## Commit index

Each item has its own commit. M16 also contains the integration fixes discovered by the batched acceptance.

| Task | Commit | Change |
|---|---|---|
| M01 | 1bd6e4f | feat(contracts): enforce versioned SDS semantic consistency |
| M02 | 45bac2b | feat(contracts): enforce implementation signatures and imports |
| M03 | 2585e7e | feat(delivery): require explicit artifact producers and complete output |
| M04 | 6e4d10d | feat(planning): reject candidates locally and preserve attempt traces |
| M05 | efdcedb | feat(planning): rank complete CTO scorecards deterministically |
| M06 | 10d155d | feat(qa): generate versioned tests from requirements and completed batches |
| M07 | aa27225 | feat(qa): route failures from evidence and aggregate repairs |
| M08 | ea4ac35 | fix(repair): version public changes and minimize invalidation |
| M09 | e3c0043 | feat(communication): persist commit-linked interface messages |
| M10 | f134066 | feat(context): bound developer inputs and explicit brief requests |
| M11 | 37eb8a5 | feat(planning): record diversity and control duplicate candidates |
| M12 | 6e03c3b | feat(runtime): close repair budgets and durable mechanism state |
| M13 | 37ff694 | feat(planning): quantify workload and queue bounded teams |
| M14 | a8c4544 | feat(rag): freeze typed retrieval packets at prompt boundaries |
| M15 | acb92c3 | feat(requirements): unify input boundary and trace requirement coverage |
| M16 | This commit | feat(mechanisms): wire independent controls and verify runtime evidence (M16) |
