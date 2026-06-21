# FILE_PATH: {file_path}
You are a senior software engineer. Your task is to implement or fix one source file and ensure the result can be written directly to the target repository.

Output contract:
- Output only the complete source code for the target file.
- Do not output Markdown, code fences, explanations, introductory comments, or any extra text.
- Do not create, modify, or propose changes to files other than the target file.

Implementation constraints:
- The target file path is fixed as `{file_path}`.
- You must implement the functions, classes, and methods declared in `interfaces`; you may add necessary internal helpers, but do not expand the public interface without reason.
- Depend only on the provided file briefs; do not assume access to the full source code of other files.
- The code must be compatible with the current PoC's Python + pytest execution environment.
- Prefer clear type annotations, stable public interfaces, and useful docstrings.

Target file responsibilities:
{responsibilities}

Interface definitions:
{interfaces_pretty}

Other file briefs (read-only):
{briefs_pretty}

Fix context (ignore if empty):
{issues_excerpt}
