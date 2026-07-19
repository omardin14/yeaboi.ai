"""Convert the app's generated Markdown to Notion blocks / Confluence storage XHTML.

The input is always Markdown produced by our own ``build_*_markdown`` builders
(standup/retro/performance/reporting exports, team profiles, sprint plans), so
only the constructs those builders emit are supported: ``#``–``###`` headings,
``-`` bullets, ``- [x]`` / ``- [ ]`` checkboxes, ``>`` blockquotes, ``---``
rules, pipe tables, ``**bold**`` / ``_italic_`` / ``*italic*`` / `` `code` ``
inline runs, and plain paragraphs.

Pure functions with no SDK imports — the publish layer (export_targets.py)
turns the returned structures into API calls.
"""

from __future__ import annotations

import html
import re

# Notion caps a single rich_text element's content at 2 000 characters.
_NOTION_TEXT_LIMIT = 2_000

_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
# Inline runs: **bold**, `code`, _italic_, *italic* (non-greedy, no nesting —
# our builders never nest emphasis).
_INLINE_RE = re.compile(r"(\*\*(.+?)\*\*|`([^`]+)`|_([^_]+)_|\*([^*]+)\*)")


def split_title(md: str) -> tuple[str, str]:
    """Split off the first ``# `` heading as the document title.

    Returns ``(title, body_without_title)``; ``("", md)`` when the document
    doesn't start with an H1.
    """
    lines = md.lstrip().split("\n")
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).lstrip("\n")
    return "", md


# ---------------------------------------------------------------------------
# Shared line-level parsing
# ---------------------------------------------------------------------------


def _iter_segments(text: str):
    """Yield ``(kind, content)`` inline segments: plain/bold/italic/code."""
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            yield "plain", text[pos : m.start()]
        if m.group(2) is not None:
            yield "bold", m.group(2)
        elif m.group(3) is not None:
            yield "code", m.group(3)
        elif m.group(4) is not None:
            yield "italic", m.group(4)
        elif m.group(5) is not None:
            yield "italic", m.group(5)
        pos = m.end()
    if pos < len(text):
        yield "plain", text[pos:]


def _split_table_row(line: str) -> list[str]:
    """Split a ``| a | b |`` table row into stripped cell strings."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------


def _rich_text(text: str) -> list[dict]:
    """Markdown inline runs → Notion rich_text array (chunked at the API limit)."""
    out: list[dict] = []
    for kind, content in _iter_segments(text):
        if not content:
            continue
        annotations = {}
        if kind == "bold":
            annotations = {"bold": True}
        elif kind == "italic":
            annotations = {"italic": True}
        elif kind == "code":
            annotations = {"code": True}
        # Chunk long runs — Notion rejects rich_text content over 2 000 chars.
        for i in range(0, len(content), _NOTION_TEXT_LIMIT):
            chunk = content[i : i + _NOTION_TEXT_LIMIT]
            item: dict = {"type": "text", "text": {"content": chunk}}
            if annotations:
                item["annotations"] = dict(annotations)
            out.append(item)
    return out


def _notion_block(block_type: str, text: str, **extra) -> dict:
    payload = {"rich_text": _rich_text(text), **extra}
    return {"object": "block", "type": block_type, block_type: payload}


def _notion_table(rows: list[list[str]]) -> dict:
    """Pipe-table rows → one Notion table block (consistent width, header row)."""
    width = max(len(r) for r in rows)
    children = []
    for row in rows:
        cells = row + [""] * (width - len(row))  # pad short rows; Notion requires equal widths
        children.append(
            {
                "object": "block",
                "type": "table_row",
                "table_row": {"cells": [_rich_text(c) for c in cells[:width]]},
            }
        )
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": children,
        },
    }


def markdown_to_notion_blocks(md: str) -> list[dict]:
    """Convert generated Markdown to a list of Notion block dicts."""
    blocks: list[dict] = []
    paragraph: list[str] = []
    table_rows: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(_notion_block("paragraph", " ".join(paragraph)))
            paragraph.clear()

    def flush_table() -> None:
        if table_rows:
            blocks.append(_notion_table(table_rows))
            table_rows.clear()

    for raw in md.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            if not _TABLE_SEPARATOR_RE.match(stripped):
                table_rows.append(_split_table_row(stripped))
            continue
        flush_table()

        if not stripped:
            flush_paragraph()
        elif stripped.startswith("### "):
            flush_paragraph()
            blocks.append(_notion_block("heading_3", stripped[4:]))
        elif stripped.startswith("## "):
            flush_paragraph()
            blocks.append(_notion_block("heading_2", stripped[3:]))
        elif stripped.startswith("# "):
            flush_paragraph()
            blocks.append(_notion_block("heading_1", stripped[2:]))
        elif stripped.startswith(("- [x] ", "- [X] ")):
            flush_paragraph()
            blocks.append(_notion_block("to_do", stripped[6:], checked=True))
        elif stripped.startswith("- [ ] "):
            flush_paragraph()
            blocks.append(_notion_block("to_do", stripped[6:], checked=False))
        elif stripped.startswith("- "):
            flush_paragraph()
            blocks.append(_notion_block("bulleted_list_item", stripped[2:]))
        elif stripped.startswith("> "):
            flush_paragraph()
            blocks.append(_notion_block("quote", stripped[2:]))
        elif stripped == "---":
            flush_paragraph()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            paragraph.append(stripped)

    flush_paragraph()
    flush_table()
    return blocks


# ---------------------------------------------------------------------------
# Confluence (storage format XHTML)
# ---------------------------------------------------------------------------


def _inline_to_xhtml(text: str) -> str:
    """Markdown inline runs → escaped XHTML with <strong>/<em>/<code>."""
    parts: list[str] = []
    for kind, content in _iter_segments(text):
        escaped = html.escape(content)
        if kind == "bold":
            parts.append(f"<strong>{escaped}</strong>")
        elif kind == "italic":
            parts.append(f"<em>{escaped}</em>")
        elif kind == "code":
            parts.append(f"<code>{escaped}</code>")
        else:
            parts.append(escaped)
    return "".join(parts)


def markdown_to_confluence_storage(md: str) -> str:
    """Convert generated Markdown to Confluence storage-format XHTML."""
    out: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    table_rows: list[list[str]] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{_inline_to_xhtml(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    def flush_table() -> None:
        if table_rows:
            width = max(len(r) for r in table_rows)
            rows_html = []
            for idx, row in enumerate(table_rows):
                tag = "th" if idx == 0 else "td"
                cells = row + [""] * (width - len(row))
                rows_html.append(
                    "<tr>" + "".join(f"<{tag}>{_inline_to_xhtml(c)}</{tag}>" for c in cells[:width]) + "</tr>"
                )
            out.append("<table><tbody>" + "".join(rows_html) + "</tbody></table>")
            table_rows.clear()

    for raw in md.split("\n"):
        stripped = raw.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            flush_list()
            if not _TABLE_SEPARATOR_RE.match(stripped):
                table_rows.append(_split_table_row(stripped))
            continue
        flush_table()

        if not stripped:
            flush_paragraph()
            flush_list()
        elif stripped.startswith("### "):
            flush_paragraph()
            flush_list()
            out.append(f"<h3>{_inline_to_xhtml(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            flush_paragraph()
            flush_list()
            out.append(f"<h2>{_inline_to_xhtml(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            flush_paragraph()
            flush_list()
            out.append(f"<h1>{_inline_to_xhtml(stripped[2:])}</h1>")
        elif stripped.startswith(("- [x] ", "- [X] ")):
            flush_paragraph()
            list_items.append(f"☑ {_inline_to_xhtml(stripped[6:])}")
        elif stripped.startswith("- [ ] "):
            flush_paragraph()
            list_items.append(f"☐ {_inline_to_xhtml(stripped[6:])}")
        elif stripped.startswith("- "):
            flush_paragraph()
            list_items.append(_inline_to_xhtml(stripped[2:]))
        elif stripped.startswith("> "):
            flush_paragraph()
            flush_list()
            out.append(f"<blockquote><p>{_inline_to_xhtml(stripped[2:])}</p></blockquote>")
        elif stripped == "---":
            flush_paragraph()
            flush_list()
            out.append("<hr />")
        else:
            flush_list()
            paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    flush_table()
    return "".join(out)
