from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


_NOISY_HEADING_PATTERNS = (
    "changelog",
    "change log",
    "release notes",
    "releases",
    "contributors",
    "contributing",
    "acknowledgements",
    "acknowledgments",
    "license",
    "citation",
    "badges",
)

_ACTIONABLE_FENCE_HINTS = (
    "pip ",
    "python ",
    "pytest",
    "curl ",
    "export ",
    "set ",
    "import ",
    "from ",
    "def ",
    "class ",
    "api",
    "config",
    "requirements",
    "usage",
    "docker",
    "make ",
)


def load_requirements_text(path: str | None, fallback: str) -> str:
    if not path:
        return fallback
    return Path(path).read_text(encoding="utf-8")


def preprocess_requirements(text: str) -> str:
    """Normalize README-style requirements into a compact planning document."""
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    skip_section_level: int | None = None
    in_fence = False
    fence_lang = ""
    fence_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_lang = line.strip()[3:].strip().lower()
                fence_lines = []
            else:
                _append_actionable_fence(kept, fence_lang, fence_lines)
                in_fence = False
                fence_lang = ""
                fence_lines = []
            continue

        if in_fence:
            fence_lines.append(line)
            continue

        heading = _parse_heading(line)
        if heading:
            level, title = heading
            if skip_section_level is not None and level <= skip_section_level:
                skip_section_level = None
            if _is_noisy_heading(title):
                skip_section_level = level
                continue
            kept.append(f"{'#' * min(level, 6)} {title}")
            continue

        if skip_section_level is not None:
            continue

        cleaned = _clean_nonessential_inline(line)
        if not cleaned:
            if kept and kept[-1] != "":
                kept.append("")
            continue

        bullet = _normalize_bullet(cleaned)
        kept.append(bullet)

    if in_fence:
        _append_actionable_fence(kept, fence_lang, fence_lines)

    return _finalize(kept)


def _parse_heading(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(2)).strip(" #")
    return len(match.group(1)), title


def _is_noisy_heading(title: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return any(pattern in normalized for pattern in _NOISY_HEADING_PATTERNS)


def _clean_nonessential_inline(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("![") or re.match(r"^\[!\[.*\]\(.*\)\]\(.*\)\s*$", stripped):
        return ""
    if re.match(r"^<img\b", stripped, re.IGNORECASE):
        return ""
    if re.match(r"^<p\s+align=", stripped, re.IGNORECASE):
        return ""
    if stripped in {"</p>", "<br>", "<br/>", "<br />"}:
        return ""
    return stripped


def _normalize_bullet(line: str) -> str:
    match = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
    if not match:
        return line
    content = match.group(3).strip()
    return f"- {content}"


def _append_actionable_fence(kept: list[str], lang: str, lines: Iterable[str]) -> None:
    body = "\n".join(lines).strip()
    if not body:
        return
    probe = f"{lang}\n{body}".lower()
    if not any(hint in probe for hint in _ACTIONABLE_FENCE_HINTS):
        return
    kept.append("```" + lang)
    kept.extend(body.split("\n"))
    kept.append("```")


def _finalize(lines: list[str]) -> str:
    compact: list[str] = []
    last_blank = True
    for line in lines:
        blank = not line.strip()
        if blank and last_blank:
            continue
        compact.append(line.rstrip())
        last_blank = blank
    while compact and not compact[-1].strip():
        compact.pop()

    if compact and not compact[0].startswith("# "):
        compact.insert(0, "# Requirements")
    return "\n".join(compact).strip() + ("\n" if compact else "")
