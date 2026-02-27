"""AI text normalization, markdown-to-HTML, and structured parsing."""
from __future__ import annotations

import re
from html import escape


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------
def normalize_text(raw) -> str:
    """Fix unicode escapes, JSON artefacts and collapse whitespace."""
    if not isinstance(raw, str):
        return ""
    text = raw
    # Literal \\uXXXX (6-char sequences left over from JSON)
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )
    text = text.replace("\\n", "\n").replace("\\r", "").replace("\\t", "  ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Inline markdown formatting
# ---------------------------------------------------------------------------
def _inline(text: str) -> str:
    """Bold, italic, code — applied *after* html-escaping."""
    t = escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"__(.+?)__", r"<strong>\1</strong>", t)
    t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
    t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


# ---------------------------------------------------------------------------
# Markdown → HTML (server-side, no JS dependency)
# ---------------------------------------------------------------------------
def md_to_html(text: str) -> str:
    """Convert markdown-like AI text to semantic HTML.

    Handles headings (##/###), unordered/ordered lists, bold, italic, code.
    """
    if not text:
        return ""
    text = normalize_text(text)
    lines = text.split("\n")
    parts: list[str] = []
    in_ul = in_ol = False
    para: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            parts.append(f"<p>{_inline(' '.join(para))}</p>")
            para = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            parts.append("</ul>")
            in_ul = False
        if in_ol:
            parts.append("</ol>")
            in_ol = False

    for raw_line in lines:
        line = raw_line.strip()

        # blank → paragraph break
        if not line:
            flush_para()
            close_lists()
            continue

        # heading
        hm = re.match(r"^(#{1,4})\s+(.+)$", line)
        if hm:
            flush_para()
            close_lists()
            lvl = min(len(hm.group(1)) + 1, 5)  # ## → h3
            parts.append(f"<h{lvl}>{escape(hm.group(2).strip())}</h{lvl}>")
            continue

        # horizontal rule
        if re.match(r"^[-*_]{3,}$", line):
            flush_para()
            close_lists()
            parts.append("<hr>")
            continue

        # unordered list
        um = re.match(r"^[*\-+]\s+(.+)$", line)
        if um:
            flush_para()
            if in_ol:
                parts.append("</ol>")
                in_ol = False
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append(f"<li>{_inline(um.group(1))}</li>")
            continue

        # ordered list
        om = re.match(r"^\d+[.)]\s+(.+)$", line)
        if om:
            flush_para()
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            if not in_ol:
                parts.append("<ol>")
                in_ol = True
            parts.append(f"<li>{_inline(om.group(1))}</li>")
            continue

        # regular text → accumulate for paragraph
        close_lists()
        para.append(line)

    flush_para()
    close_lists()
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Structured sections
# ---------------------------------------------------------------------------
def parse_ai_sections(raw_text: str) -> list[dict]:
    """Split AI text into ``[{title, html}]`` by heading boundaries."""
    text = normalize_text(raw_text) if raw_text else ""
    if not text:
        return []

    sections: list[dict] = []
    cur_title = "Resumo"
    cur_lines: list[str] = []

    def save():
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append({"title": cur_title, "html": md_to_html(body)})

    for line in text.split("\n"):
        hm = re.match(r"^#{1,4}\s+(.+)$", line.strip())
        if hm:
            save()
            cur_title = hm.group(1).strip()
            cur_lines = []
        else:
            cur_lines.append(line)

    save()
    return sections


# ---------------------------------------------------------------------------
# Recommendation extraction
# ---------------------------------------------------------------------------
_RE_NOGO = re.compile(r"\bno[- ]?go\b", re.IGNORECASE)
_RE_GO_RESSALVAS = re.compile(r"\bgo\s+(com\s+)?ressalvas?\b", re.IGNORECASE)
_RE_GO = re.compile(r"\bgo\b", re.IGNORECASE)


def extract_recommendation(content) -> str | None:
    """Return ``'go'``, ``'go_ressalvas'``, ``'nogo'`` or ``None``."""
    text = _text_from_content(content)
    if not text:
        return None

    # Check structured key first
    if isinstance(content, dict):
        rec = str(content.get("recomendacao", ""))
        r = _match_rec(rec)
        if r:
            return r

    return _match_rec(text)


def _match_rec(text: str) -> str | None:
    if _RE_NOGO.search(text):
        return "nogo"
    if _RE_GO_RESSALVAS.search(text):
        return "go_ressalvas"
    if _RE_GO.search(text):
        return "go"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _text_from_content(content) -> str:
    """Extract plain text from AISummary.content (dict or str)."""
    if isinstance(content, str):
        return normalize_text(content)
    if isinstance(content, dict):
        for key in ("text", "raw_response", "resumo"):
            val = content.get(key)
            if isinstance(val, str) and val:
                return normalize_text(val)
    return ""


def format_brl(value) -> str:
    """Format a numeric value as ``R$ 1.234,56``."""
    if value is None:
        return "\u2014"
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"
