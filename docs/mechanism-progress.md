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
- [ ] M09: Durable interface communication
- [ ] M10: Bounded context and briefing
- [ ] M11: Planning diversity
- [ ] M12: Closed resource state
- [ ] M13: Workload-aware allocation
- [ ] M14: Retrieval information contracts
- [ ] M15: Requirement traceability
- [ ] M16: Mechanism controls and acceptance

## Batch validation

Pending.

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
