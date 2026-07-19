"""Tests for export_targets — the Notion/Confluence publish layer (mocked SDK clients)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from yeaboi.export_targets import (
    CONFLUENCE_PATH_HINT,
    NOTION_PATH_HINT,
    PublishResult,
    localize_images,
    publish_markdown,
    publish_to_confluence,
    publish_to_notion,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "NOTION_TOKEN",
        "NOTION_ROOT_PAGE_ID",
        "NOTION_EXPORT_PARENT_PAGE_ID",
        "CONFLUENCE_SPACE_KEY",
        "CONFLUENCE_EXPORT_PARENT_PAGE_ID",
        "CONFLUENCE_BASE_URL",
        "JIRA_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


class TestPublishToNotion:
    def test_no_page_at_all_blocks_with_hint(self):
        result = publish_to_notion("T", "# T\n\nbody")
        assert result.ok is False
        assert result.message == NOTION_PATH_HINT

    def test_root_page_fallback_publishes(self, monkeypatch):
        # No dedicated exports page — the root page from setup is the parent.
        monkeypatch.setenv("NOTION_ROOT_PAGE_ID", "root-1")
        client = MagicMock()
        client.pages.create.return_value = {"id": "pg", "url": ""}
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("T", "body")
        assert result.ok is True
        assert client.pages.create.call_args.kwargs["parent"] == {"page_id": "root-1"}

    def test_missing_client_blocks(self, monkeypatch):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "abc123")
        with patch("yeaboi.tools.notion._make_notion_client", return_value=None):
            result = publish_to_notion("T", "body")
        assert result.ok is False
        assert "not configured" in result.message

    def test_success_creates_page_under_parent(self, monkeypatch):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        client = MagicMock()
        client.pages.create.return_value = {"id": "pg", "url": "https://notion.so/pg"}
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("My Report", "## Section\n\ntext")
        assert result.ok is True
        assert result.url == "https://notion.so/pg"
        kwargs = client.pages.create.call_args.kwargs
        assert kwargs["parent"] == {"page_id": "parent-1"}
        assert kwargs["properties"]["title"][0]["text"]["content"] == "My Report"
        client.blocks.children.append.assert_not_called()

    def test_over_100_blocks_batched(self, monkeypatch):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        client = MagicMock()
        client.pages.create.return_value = {"id": "pg", "url": ""}
        md = "\n\n".join(f"para {i}" for i in range(250))  # 250 paragraph blocks
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("Big", md)
        assert result.ok is True
        assert len(client.pages.create.call_args.kwargs["children"]) == 100
        appends = client.blocks.children.append.call_args_list
        assert [len(c.kwargs["children"]) for c in appends] == [100, 50]

    def test_api_error_never_raises(self, monkeypatch):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        client = MagicMock()
        client.pages.create.side_effect = RuntimeError("boom")
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("T", "body")
        assert result.ok is False
        assert "boom" in result.message

    def test_images_uploaded_and_referenced(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        img = tmp_path / "chart.png"
        img.write_bytes(b"\x89PNG fake")
        client = MagicMock()
        client.file_uploads.create.return_value = {"id": "up-42"}
        client.pages.create.return_value = {"id": "pg", "url": ""}
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("T", f"![Chart]({img})\n\ntext")
        assert result.ok is True
        client.file_uploads.create.assert_called_once_with(
            mode="single_part", filename="chart.png", content_type="image/png"
        )
        assert client.file_uploads.send.call_args.kwargs["file_upload_id"] == "up-42"
        blocks = client.pages.create.call_args.kwargs["children"]
        assert blocks[0]["type"] == "image"
        assert blocks[0]["image"]["file_upload"] == {"id": "up-42"}

    def test_image_upload_failure_degrades(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        img = tmp_path / "chart.png"
        img.write_bytes(b"x")
        client = MagicMock()
        client.file_uploads.create.side_effect = RuntimeError("upload down")
        client.pages.create.return_value = {"id": "pg", "url": ""}
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("T", f"![Chart]({img})")
        assert result.ok is True  # page still publishes, image degrades
        blocks = client.pages.create.call_args.kwargs["children"]
        assert blocks[0]["type"] == "paragraph"  # italic placeholder

    def test_missing_image_file_skipped(self, monkeypatch):
        monkeypatch.setenv("NOTION_EXPORT_PARENT_PAGE_ID", "parent-1")
        client = MagicMock()
        client.pages.create.return_value = {"id": "pg", "url": ""}
        with patch("yeaboi.tools.notion._make_notion_client", return_value=client):
            result = publish_to_notion("T", "![gone](/nope/missing.png)")
        assert result.ok is True
        client.file_uploads.create.assert_not_called()


class TestPublishToConfluence:
    def test_missing_space_blocks_with_hint(self):
        result = publish_to_confluence("T", "body")
        assert result.ok is False
        assert result.message == CONFLUENCE_PATH_HINT

    def test_missing_client_blocks(self, monkeypatch):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=None):
            result = publish_to_confluence("T", "body")
        assert result.ok is False
        assert "not configured" in result.message

    def test_success_timestamps_title_and_passes_parent(self, monkeypatch):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        monkeypatch.setenv("CONFLUENCE_EXPORT_PARENT_PAGE_ID", "999")
        monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://org.atlassian.net")
        conf = MagicMock()
        conf.create_page.return_value = {"id": "42", "_links": {"webui": "/wiki/x"}}
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            result = publish_to_confluence("Retro — proj", "## Went well\n\n- a")
        assert result.ok is True
        kwargs = conf.create_page.call_args.kwargs
        assert kwargs["space"] == "SP"
        assert kwargs["parent_id"] == "999"
        # Duplicate titles are rejected by Confluence — title must be timestamped.
        assert kwargs["title"].startswith("Retro — proj · ")
        assert kwargs["title"] != "Retro — proj"
        assert "<h2>Went well</h2>" in kwargs["body"]
        assert result.url == "https://org.atlassian.net/wiki/x"

    def test_no_parent_defaults_to_none(self, monkeypatch):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        conf = MagicMock()
        conf.create_page.return_value = {"id": "42", "_links": {}}
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            result = publish_to_confluence("T", "body")
        assert result.ok is True
        assert conf.create_page.call_args.kwargs["parent_id"] is None

    def test_error_never_raises(self, monkeypatch):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        conf = MagicMock()
        conf.create_page.side_effect = RuntimeError("down")
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            result = publish_to_confluence("T", "body")
        assert result.ok is False
        assert "down" in result.message

    def test_images_attached_after_create(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        img = tmp_path / "shot.png"
        img.write_bytes(b"x")
        conf = MagicMock()
        conf.create_page.return_value = {"id": "77", "_links": {}}
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            result = publish_to_confluence("T", f"![Screenshot]({img})")
        assert result.ok is True
        # Body references the attachment macro; file attached to the new page.
        assert '<ri:attachment ri:filename="shot.png" />' in conf.create_page.call_args.kwargs["body"]
        conf.attach_file.assert_called_once_with(str(img), name="shot.png", page_id="77")

    def test_duplicate_image_basenames_deduped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        one, two = tmp_path / "a" / "img.png", tmp_path / "b" / "img.png"
        one.write_bytes(b"1")
        two.write_bytes(b"2")
        conf = MagicMock()
        conf.create_page.return_value = {"id": "77", "_links": {}}
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            publish_to_confluence("T", f"![a]({one})\n![b]({two})")
        names = [c.kwargs["name"] for c in conf.attach_file.call_args_list]
        assert names == ["img.png", "img-1.png"]

    def test_attach_failure_keeps_page(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "SP")
        img = tmp_path / "shot.png"
        img.write_bytes(b"x")
        conf = MagicMock()
        conf.create_page.return_value = {"id": "77", "_links": {}}
        conf.attach_file.side_effect = RuntimeError("attach down")
        with patch("yeaboi.tools.confluence._make_confluence_client", return_value=conf):
            result = publish_to_confluence("T", f"![Screenshot]({img})")
        assert result.ok is True


class TestLocalizeImages:
    def test_copies_and_relinks(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        img = src / "shot.png"
        img.write_bytes(b"png")
        dest = tmp_path / "export"
        dest.mkdir()

        md = localize_images(f"# T\n\n![Screenshot]({img})", dest)
        assert "![Screenshot](images/shot.png)" in md
        assert (dest / "images" / "shot.png").read_bytes() == b"png"

    def test_missing_image_left_alone(self, tmp_path):
        md = localize_images("![x](/nope/gone.png)", tmp_path)
        assert "![x](/nope/gone.png)" in md
        assert not (tmp_path / "images").exists()

    def test_no_images_no_dir(self, tmp_path):
        assert localize_images("plain text", tmp_path) == "plain text"
        assert not (tmp_path / "images").exists()


class TestPublishMarkdownDispatch:
    def test_dispatches_to_notion(self):
        with patch("yeaboi.export_targets.publish_to_notion") as pn:
            pn.return_value = PublishResult(ok=True, message="ok")
            result = publish_markdown("notion", title="T", markdown="m")
        pn.assert_called_once_with("T", "m")
        assert result.ok is True

    def test_dispatches_to_confluence(self):
        with patch("yeaboi.export_targets.publish_to_confluence") as pc:
            pc.return_value = PublishResult(ok=True, message="ok")
            publish_markdown("confluence", title="T", markdown="m")
        pc.assert_called_once_with("T", "m")

    def test_unknown_destination(self):
        result = publish_markdown("carrier-pigeon", title="T", markdown="m")
        assert result.ok is False
        assert "carrier-pigeon" in result.message
