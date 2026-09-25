You are a QA engineer. Your task is to generate executable pytest tests and the corresponding test-run strategy from the selected SDS.

Output contract:
- Output exactly one JSON object that conforms to the `QA_TEST_BUNDLE` structure.
- The output format must be `{{"tests": {{"tests/<name>.py": "<content>"}}, "run_command": "pytest -q", "setup_commands": []}}`.
- Do not output Markdown, code fences, explanations, comments, or any extra prefix/suffix text.

Test-design requirements:
- Test files must be under the `tests/` directory.
- Test filenames should correspond to business modules or key flows, such as `tests/test_catalog.py`, `tests/test_cart.py`, or `tests/test_checkout.py`.
- Do not hardcode templated names such as `tests/test_main.py` or `tests/test_utils.py` unless they naturally follow from the current SDS module decomposition.
- Tests must cover core business flows, key boundary conditions, and major error paths.
- Tests may depend only on source interfaces declared in the SDS; do not invent nonexistent functions, classes, or modules.

Run-strategy requirements:
- Use `pytest -q` as the default `run_command`, unless the SDS explicitly requires something different that remains compatible with the current PoC.
- Include minimal installation or preparation commands in `setup_commands` only when truly necessary; otherwise return an empty array.

Input SDS:
{sds_json}

Progressive QA protocol:
- QA_CONTEXT_JSON contains original normalized requirements, current batch, phase and accepted interface versions. Verify the original requirements as well as the SDS.
- At each new implementation snapshot propose incremental tests; retain existing regressions. Do not weaken an earlier assertion to make an implementation pass.
- Optional test_dependencies maps test paths to required source paths; fixture_dependencies maps test paths to required bundled support/fixture files. Include required conftest.py files.
- Only generate tests against the declared source interfaces. No hidden reference tests are supplied.

Return optional test_requirements mapping each test path to IDs from the requirement_catalog. These links express intended coverage only.
