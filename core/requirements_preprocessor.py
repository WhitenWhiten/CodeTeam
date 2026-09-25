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


def requirements_document(text: str, enabled: bool = True) -> dict:
    """One CLI/API input boundary with original source and block decisions."""
    import hashlib
    lines=(text or "").replace("\r\n","\n").replace("\r","\n").split("\n")
    records=[]; kept=[]; occurrences={}; skip_level=None; index=0
    fence_pattern=r"^\s*([\x60]{3,}|~{3,})(.*)$"
    while index<len(lines):
        start=index
        line=lines[index].rstrip()
        fence=re.match(fence_pattern,line)
        heading=_parse_heading(line)
        if fence:
            marker=fence.group(1); index+=1
            while index<len(lines) and not lines[index].strip().startswith(marker): index+=1
            if index<len(lines): index+=1
            block=lines[start:index]; kind="example"
        elif heading:
            block=[line]; index+=1; kind="heading"
            if skip_level is not None and heading[0]<=skip_level: skip_level=None
            if enabled and _is_noisy_heading(heading[1]): skip_level=heading[0]
        else:
            index+=1
            while index<len(lines) and lines[index].strip() and not _parse_heading(lines[index]) and not re.match(fence_pattern,lines[index]): index+=1
            block=lines[start:index]; kind="requirement"
        original="\n".join(block)
        canonical=original.strip()
        if not canonical:
            if kept and kept[-1]!="": kept.append("")
            continue
        digest=hashlib.sha256(canonical.encode()).hexdigest()[:12]
        occurrences[digest]=occurrences.get(digest,0)+1
        rid=f"REQ-{digest}-{occurrences[digest]}"
        reason="preserved"; rendered=original
        if enabled and skip_level is not None:
            reason="noisy_section_including_descendants"; rendered=""
        elif enabled and not fence:
            cleaned=[_normalize_bullet(_clean_nonessential_inline(x)) for x in block]
            rendered="\n".join(cleaned).strip()
            if not rendered: reason="decorative_inline_content"
            elif rendered!=original: reason="normalized_inline_content"
        if rendered: kept.extend(rendered.split("\n")); kept.append("")
        records.append({"id":rid,"kind":kind,"start_line":start+1,"end_line":index,
                        "status":"retained" if rendered else "removed","reason":reason,
                        "original":original,"text":rendered})
    normalized=_finalize(kept) if enabled else text
    return {"version":1,"original_sha256":hashlib.sha256((text or "").encode()).hexdigest(),
            "normalized":normalized,"records":records,"preprocessing_enabled":enabled}


def preprocess_requirements(text: str) -> str:
    return requirements_document(text)["normalized"]


def requirement_catalog(document):
    return [{k:r[k] for k in ("id","kind","start_line","end_line","text")} for r in document["records"] if r["status"]=="retained"]


def coverage_report(document,sds,test_requirements=None):
    ids={r["id"] for r in requirement_catalog(document)}
    files={s["path"]:s.get("requirement_ids",[]) for s in sds["file_specs"]}
    tests=dict(test_requirements or {})
    unknown=sorted({rid for refs in list(files.values())+list(tests.values()) for rid in refs}-ids)
    if unknown: raise ValueError(f"Unknown requirement references: {unknown}")
    return {"files":files,"tests":tests,"unmapped_to_files":sorted(ids-{x for refs in files.values() for x in refs}),
            "unmapped_to_tests":sorted(ids-{x for refs in tests.values() for x in refs}),
            "interpretation":"Declared trace links, not a proof of behavioral coverage"}


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
