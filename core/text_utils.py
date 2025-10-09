# demo/core/text_utils.py
import re
import html

def strip_code_fences(text: str, preferred_langs=("python", "py")) -> str:
    """
    Remove Markdown/HTML code fences and return the inner code.
    - If multiple fences exist, prefer ones labeled with preferred_langs.
    - Otherwise pick the longest fenced block.
    - Handles <pre><code> HTML blocks.
    - Falls back to removing leading/trailing backticks if present.
    """
    if not isinstance(text, str):
        return text

    s = text.strip()

    # HTML <pre><code> blocks
    pre_blocks = re.findall(r"<pre>\s*<code[^>]*>(.*?)</code>\s*</pre>", s, flags=re.DOTALL | re.IGNORECASE)
    if pre_blocks:
        code = html.unescape(pre_blocks[0].strip())
        return code

    # Markdown fenced blocks: ```lang\n...code...\n```
    fenced = list(re.finditer(r"```([^\n]*)\n(.*?)\n```", s, flags=re.DOTALL))
    if fenced:
        for m in fenced:
            lang = (m.group(1) or "").strip().lower()
            if lang in preferred_langs:
                return m.group(2).strip()
        longest = max(fenced, key=lambda m: len(m.group(2) or ""))
        return (longest.group(2) or "").strip()

    # Triple tilde fences: ~~~
    fenced_tilde = list(re.finditer(r"~~~([^\n]*)\n(.*?)\n~~~", s, flags=re.DOTALL))
    if fenced_tilde:
        for m in fenced_tilde:
            lang = (m.group(1) or "").strip().lower()
            if lang in preferred_langs:
                return m.group(2).strip()
        longest = max(fenced_tilde, key=lambda m: len(m.group(2) or ""))
        return (longest.group(2) or "").strip()

    # Simple fallback: remove single-line fences if someone pasted raw ```python and ending ```
    if s.startswith("```"):
        lines = s.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    return s
