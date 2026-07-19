"""Tests for markdown_convert — generated Markdown → Notion blocks / Confluence XHTML."""

from __future__ import annotations

from yeaboi.markdown_convert import (
    _NOTION_TEXT_LIMIT,
    extract_image_paths,
    markdown_to_confluence_storage,
    markdown_to_notion_blocks,
    md_table_cell,
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

    def test_hard_break_keeps_lines_apart(self):
        # Trailing two spaces = hard break (standup's **Sprint:**/**Confidence:** header).
        blocks = markdown_to_notion_blocks("**Sprint:** 3  \n**Confidence:** High")
        assert len(blocks) == 1
        text = "".join(r["text"]["content"] for r in blocks[0]["paragraph"]["rich_text"])
        assert text == "Sprint: 3\nConfidence: High"

    def test_nested_bullets_become_children(self):
        blocks = markdown_to_notion_blocks("- top\n  - nested one\n  - nested two\n- next top")
        assert [b["type"] for b in blocks] == ["bulleted_list_item", "bulleted_list_item"]
        children = blocks[0]["bulleted_list_item"]["children"]
        assert [c["type"] for c in children] == ["bulleted_list_item", "bulleted_list_item"]
        assert children[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "nested one"
        assert "children" not in blocks[1]["bulleted_list_item"]

    def test_given_when_then_stays_in_one_bullet(self):
        # The plan's acceptance-criteria continuation lines must not detach.
        md = "- **Given** a user\n  **When** they click\n  **Then** it works"
        blocks = markdown_to_notion_blocks(md)
        assert len(blocks) == 1
        text = "".join(r["text"]["content"] for r in blocks[0]["bulleted_list_item"]["rich_text"])
        assert text == "Given a user\nWhen they click\nThen it works"

    def test_consecutive_quote_lines_merge(self):
        blocks = markdown_to_notion_blocks("> line one\n> line two\n>   - `KEY-1` nested")
        assert len(blocks) == 1
        text = "".join(r["text"]["content"] for r in blocks[0]["quote"]["rich_text"])
        assert text == "line one\nline two\n• KEY-1 nested"

    def test_numbered_list(self):
        blocks = markdown_to_notion_blocks("1. first\n2. second")
        assert [b["type"] for b in blocks] == ["numbered_list_item"] * 2
        assert blocks[1]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "second"

    def test_links(self):
        blocks = markdown_to_notion_blocks("See [the docs](https://example.com) now")
        runs = blocks[0]["paragraph"]["rich_text"]
        link = next(r for r in runs if r["text"].get("link"))
        assert link["text"]["content"] == "the docs"
        assert link["text"]["link"] == {"url": "https://example.com"}

    def test_notices_section_becomes_callout(self):
        md = "## ⚠ Notices\n- Jira returned 401\n- LLM not configured\n\n## Team Summary\n- fine"
        blocks = markdown_to_notion_blocks(md)
        assert [b["type"] for b in blocks] == ["heading_2", "callout", "heading_2", "bulleted_list_item"]
        callout = blocks[1]["callout"]
        assert callout["icon"] == {"type": "emoji", "emoji": "⚠️"}
        assert callout["color"] == "yellow_background"
        text = "".join(r["text"]["content"] for r in callout["rich_text"])
        assert text == "Jira returned 401\nLLM not configured"

    def test_image_with_upload_id(self):
        blocks = markdown_to_notion_blocks("![Velocity](/tmp/v.png)", image_ids={"/tmp/v.png": "up-1"})
        assert blocks[0]["type"] == "image"
        assert blocks[0]["image"]["file_upload"] == {"id": "up-1"}
        assert blocks[0]["image"]["caption"][0]["text"]["content"] == "Velocity"

    def test_image_without_mapping_degrades(self):
        blocks = markdown_to_notion_blocks("![Velocity](/tmp/v.png)")
        assert blocks[0]["type"] == "paragraph"
        run = blocks[0]["paragraph"]["rich_text"][0]
        assert run["text"]["content"] == "[image: Velocity]"
        assert run["annotations"] == {"italic": True}


class TestMdTableCell:
    def test_pipes_and_newlines_sanitized(self):
        assert md_table_cell("a | b\nc") == "a \\ b c"

    def test_whitespace_collapsed(self):
        assert md_table_cell("  spaced   out  ") == "spaced out"

    def test_non_string_coerced(self):
        assert md_table_cell(42) == "42"


class TestExtractImagePaths:
    def test_ordered_and_deduped(self):
        md = "![a](/p/one.png)\ntext\n![b](/p/two.png)\n![c](/p/one.png)"
        assert extract_image_paths(md) == ["/p/one.png", "/p/two.png"]

    def test_path_with_spaces(self):
        assert extract_image_paths("![x](/My Data/img 1.png)") == ["/My Data/img 1.png"]

    def test_none(self):
        assert extract_image_paths("plain text\n- bullet") == []


class TestConfluenceStorage:
    def test_headings(self):
        out = markdown_to_confluence_storage("# One\n## Two\n### Three")
        assert "<h1>One</h1>" in out
        assert "<h2>Two</h2>" in out
        assert "<h3>Three</h3>" in out

    def test_checkboxes_become_native_task_list(self):
        out = markdown_to_confluence_storage("- plain\n- [x] done\n- [ ] open")
        assert "<ul><li>plain</li></ul>" in out
        assert (
            "<ac:task-list>"
            "<ac:task><ac:task-status>complete</ac:task-status><ac:task-body>done</ac:task-body></ac:task>"
            "<ac:task><ac:task-status>incomplete</ac:task-status><ac:task-body>open</ac:task-body></ac:task>"
            "</ac:task-list>" in out
        )

    def test_nested_bullets(self):
        out = markdown_to_confluence_storage("- top\n  - nested\n- next")
        assert out == "<ul><li>top<ul><li>nested</li></ul></li><li>next</li></ul>"

    def test_numbered_list(self):
        out = markdown_to_confluence_storage("1. first\n2. second")
        assert out == "<ol><li>first</li><li>second</li></ol>"

    def test_hard_break_in_paragraph(self):
        out = markdown_to_confluence_storage("**Sprint:** 3  \n**Confidence:** High")
        assert out == "<p><strong>Sprint:</strong> 3<br /><strong>Confidence:</strong> High</p>"

    def test_continuation_line_stays_in_list_item(self):
        out = markdown_to_confluence_storage("- **Given** a user\n  **When** they click")
        assert out == "<ul><li><strong>Given</strong> a user<br /><strong>When</strong> they click</li></ul>"

    def test_quote_lines_merge_with_nested_bullets(self):
        out = markdown_to_confluence_storage("> line one\n>   - `K-1` item")
        assert out == "<blockquote><p>line one<br />• <code>K-1</code> item</p></blockquote>"

    def test_link(self):
        out = markdown_to_confluence_storage("See [docs](https://example.com/x?a=1&b=2)")
        assert '<a href="https://example.com/x?a=1&amp;b=2">docs</a>' in out

    def test_notices_section_becomes_warning_panel(self):
        out = markdown_to_confluence_storage("## ⚠ Notices\n- Jira 401\n\n## Next\npara")
        assert (
            '<ac:structured-macro ac:name="warning"><ac:rich-text-body>'
            "<ul><li>Jira 401</li></ul>"
            "</ac:rich-text-body></ac:structured-macro>" in out
        )
        assert "<h2>Next</h2>" in out

    def test_image_with_attachment_mapping(self):
        out = markdown_to_confluence_storage("![Chart](/tmp/v.png)", image_filenames={"/tmp/v.png": "v.png"})
        assert out == '<ac:image ac:alt="Chart"><ri:attachment ri:filename="v.png" /></ac:image>'

    def test_image_without_mapping_degrades(self):
        out = markdown_to_confluence_storage("![Chart](/tmp/v.png)")
        assert out == "<p><em>[image: Chart]</em></p>"

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
