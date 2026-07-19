"""Tests for markdown_convert — generated Markdown → Notion blocks / Confluence XHTML."""

from __future__ import annotations

from yeaboi.markdown_convert import (
    _NOTION_TEXT_LIMIT,
    markdown_to_confluence_storage,
    markdown_to_notion_blocks,
    split_title,
)


class TestSplitTitle:
    def test_h1_becomes_title(self):
        title, body = split_title("# Daily Standup — 2026-07-18\n\nHello")
        assert title == "Daily Standup — 2026-07-18"
        assert body == "Hello"

    def test_no_h1_returns_empty_title(self):
        title, body = split_title("Just a paragraph")
        assert title == ""
        assert body == "Just a paragraph"

    def test_empty_input(self):
        assert split_title("") == ("", "")


class TestNotionBlocks:
    def test_headings(self):
        blocks = markdown_to_notion_blocks("# One\n## Two\n### Three")
        assert [b["type"] for b in blocks] == ["heading_1", "heading_2", "heading_3"]
        assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "One"

    def test_bullets_and_checkboxes(self):
        blocks = markdown_to_notion_blocks("- plain\n- [x] done\n- [ ] open")
        assert [b["type"] for b in blocks] == ["bulleted_list_item", "to_do", "to_do"]
        assert blocks[1]["to_do"]["checked"] is True
        assert blocks[2]["to_do"]["checked"] is False

    def test_quote_and_divider(self):
        blocks = markdown_to_notion_blocks("> wisdom\n\n---")
        assert [b["type"] for b in blocks] == ["quote", "divider"]

    def test_paragraph_lines_join(self):
        blocks = markdown_to_notion_blocks("line one\nline two\n\nsecond para")
        assert [b["type"] for b in blocks] == ["paragraph", "paragraph"]
        assert blocks[0]["paragraph"]["rich_text"][0]["text"]["content"] == "line one line two"

    def test_inline_annotations(self):
        blocks = markdown_to_notion_blocks("Some **bold** and _ital_ and `code`.")
        runs = blocks[0]["paragraph"]["rich_text"]
        kinds = [(r["text"]["content"], r.get("annotations", {})) for r in runs]
        assert ("bold", {"bold": True}) in kinds
        assert ("ital", {"italic": True}) in kinds
        assert ("code", {"code": True}) in kinds

    def test_table_block_shape(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 |"
        blocks = markdown_to_notion_blocks(md)
        assert len(blocks) == 1
        table = blocks[0]["table"]
        assert table["table_width"] == 2
        assert table["has_column_header"] is True
        rows = table["children"]
        assert len(rows) == 3  # header + 2 data rows; separator row dropped
        # Short row padded to table_width
        assert len(rows[2]["table_row"]["cells"]) == 2

    def test_long_text_chunked(self):
        blocks = markdown_to_notion_blocks("x" * (_NOTION_TEXT_LIMIT + 100))
        runs = blocks[0]["paragraph"]["rich_text"]
        assert len(runs) == 2
        assert all(len(r["text"]["content"]) <= _NOTION_TEXT_LIMIT for r in runs)

    def test_empty_input(self):
        assert markdown_to_notion_blocks("") == []


class TestConfluenceStorage:
    def test_headings(self):
        out = markdown_to_confluence_storage("# One\n## Two\n### Three")
        assert "<h1>One</h1>" in out
        assert "<h2>Two</h2>" in out
        assert "<h3>Three</h3>" in out

    def test_list_and_checkboxes(self):
        out = markdown_to_confluence_storage("- plain\n- [x] done\n- [ ] open")
        assert "<ul><li>plain</li><li>☑ done</li><li>☐ open</li></ul>" == out

    def test_quote_divider_paragraph(self):
        out = markdown_to_confluence_storage("> wisdom\n\n---\n\npara")
        assert "<blockquote><p>wisdom</p></blockquote>" in out
        assert "<hr />" in out
        assert "<p>para</p>" in out

    def test_inline_formatting(self):
        out = markdown_to_confluence_storage("**bold** _ital_ `code`")
        assert "<strong>bold</strong>" in out
        assert "<em>ital</em>" in out
        assert "<code>code</code>" in out

    def test_table(self):
        out = markdown_to_confluence_storage("| A | B |\n|---|---|\n| 1 | 2 |")
        assert "<table><tbody>" in out
        assert "<th>A</th><th>B</th>" in out
        assert "<td>1</td><td>2</td>" in out

    def test_xhtml_escaping(self):
        out = markdown_to_confluence_storage("a <script> & friends")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
        assert "&amp;" in out

    def test_empty_input(self):
        assert markdown_to_confluence_storage("") == ""
