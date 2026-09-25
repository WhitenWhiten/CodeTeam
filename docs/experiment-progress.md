# Revision infrastructure implementation

Scope: requested items 1, 2, 3 and 7; no experiment-result data edits.

- [x] 1. Versioned experiment protocol, batch runner, provenance and artifact recovery.
- [x] 2. Independent SketchBLEU / NL2Repo evaluation and result contracts.
- [x] 3. Cost, role attribution, sampling seeds and cumulative resource records.
- [x] 7. Independent matched SFT preparation, training and checkpoint validation.

Item 7 includes real CPU full/LoRA training and saved-checkpoint reload tests.
The paper's combined QLoRA/ZeRO-3/LongLoRA GPU recipe remains unverified and is
not claimed as implemented; see training-guide.md for supported paths and gaps.

Verification on 2026-09-25:

- Base-environment full suite: 124 passed, 1 optional-training module skipped.
- Training environment: 7 preparation/export tests and 3 real-training tests
  passed together; an additional real optimizer-checkpoint recovery test passed.
- Wheel installation outside the checkout: runtime mock generation and all three
  installed CLI help entrypoints passed.
- Official evaluator subprocess contracts use fixtures. Full benchmark scoring,
  remote API calls and four-GPU 72B training were not executed in this change.
