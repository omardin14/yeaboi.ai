"""Publish generated Markdown exports to Notion / Confluence.

# See README: "Tools" — this module deliberately bypasses the @tool wrappers in
tools/notion.py and tools/confluence.py. Those wrappers are for the LLM agent:
they return user-facing strings (success is indistinguishable from failure
programmatically), accept only plain text bodies, and can't batch. The TUI
Export buttons need structured success/failure and rich formatting, so this
layer uses the same client factories directly with markdown_convert output.

Every function here is best-effort and NEVER raises — failures become a
``PublishResult(ok=False, message=...)`` the TUI shows as a status line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from yeaboi.config import (
    get_confluence_base_url,
    get_confluence_export_parent_page_id,
    get_confluence_space_key,
    get_notion_export_parent_page_id,
)
from yeaboi.markdown_convert import markdown_to_confluence_storage, markdown_to_notion_blocks

logger = logging.getLogger(__name__)

# Notion rejects pages.create / blocks.children.append calls with more than
# 100 children — long documents (plans, team profiles) are appended in chunks.
_NOTION_BLOCK_BATCH = 100

DEST_NOTION = "notion"
DEST_CONFLUENCE = "confluence"

# Shown when the integration works but publishing is impossible: Notion can't
# create top-level pages (needs a root or exports page), and a Confluence page
# must live in a space. Both are collected in Setup → Docs.
NOTION_PATH_HINT = "Add a Notion page in Setup → Docs — Notion needs a page to publish under"
CONFLUENCE_PATH_HINT = "Add a Confluence space key in Setup → Docs"


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a publish attempt — message is ready for the TUI status line."""

    ok: bool
    message: str
    url: str = ""


def publish_to_notion(title: str, markdown: str) -> PublishResult:
    """Create a Notion page with the markdown content under the exports page (or the root page)."""
    logger.info("Notion export requested: %r", title)
    # Exports page from setup, falling back to the root page — see the getter.
    parent = get_notion_export_parent_page_id()
    if not parent:
        logger.warning("Notion export blocked: no exports page or root page configured")
        return PublishResult(ok=False, message=NOTION_PATH_HINT)

    # Lazy import — the SDK and its config guards live with the tool module.
    from yeaboi.tools.notion import _make_notion_client

    client = _make_notion_client()
    if client is None:
        logger.warning("Notion export blocked: NOTION_TOKEN not configured")
        return PublishResult(ok=False, message="Notion is not configured — set NOTION_TOKEN in Settings")

    blocks = markdown_to_notion_blocks(markdown)
    try:
        page = client.pages.create(
            parent={"page_id": parent},
            properties={"title": [{"type": "text", "text": {"content": title}}]},
            children=blocks[:_NOTION_BLOCK_BATCH],
        )
        page_id = page.get("id", "")
        # Append the rest in 100-block batches (Notion's per-call children limit).
        for i in range(_NOTION_BLOCK_BATCH, len(blocks), _NOTION_BLOCK_BATCH):
            client.blocks.children.append(page_id, children=blocks[i : i + _NOTION_BLOCK_BATCH])
        url = page.get("url", "")
        logger.info("Notion export succeeded: %r (%d blocks) -> %s", title, len(blocks), url)
        return PublishResult(ok=True, message=f"Exported to Notion: {title}", url=url)
    except Exception as e:  # noqa: BLE001 — publish is best-effort, never crash the TUI
        try:
            from notion_client.errors import APIResponseError

            from yeaboi.tools.notion import _notion_error_msg

            if isinstance(e, APIResponseError):
                msg = _notion_error_msg(e)
            else:
                msg = f"Notion export failed: {e}"
        except Exception:
            msg = f"Notion export failed: {e}"
        logger.warning("Notion export failed for %r: %s", title, e)
        return PublishResult(ok=False, message=msg)


def publish_to_confluence(title: str, markdown: str) -> PublishResult:
    """Create a Confluence page with the markdown content in the configured space."""
    logger.info("Confluence export requested: %r", title)
    space = get_confluence_space_key()
    if not space:
        logger.warning("Confluence export blocked: CONFLUENCE_SPACE_KEY not set")
        return PublishResult(ok=False, message=CONFLUENCE_PATH_HINT)

    from yeaboi.tools.confluence import _make_confluence_client

    conf = _make_confluence_client()
    if conf is None:
        logger.warning("Confluence export blocked: credentials not configured")
        return PublishResult(
            ok=False, message="Confluence is not configured — set the Confluence credentials in Settings"
        )

    # Confluence rejects duplicate titles within a space, and re-exporting the
    # same report is the normal case — timestamp the title to keep it unique.
    stamped_title = f"{title} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        page = conf.create_page(
            space=space,
            title=stamped_title,
            body=markdown_to_confluence_storage(markdown),
            parent_id=get_confluence_export_parent_page_id() or None,
        )
        page_id = page.get("id", "")
        base_url = (get_confluence_base_url() or "").rstrip("/")
        web_ui = page.get("_links", {}).get("webui", f"/wiki/pages/{page_id}")
        url = f"{base_url}{web_ui}"
        logger.info("Confluence export succeeded: %r -> %s", stamped_title, url)
        return PublishResult(ok=True, message=f"Exported to Confluence: {stamped_title}", url=url)
    except Exception as e:  # noqa: BLE001 — publish is best-effort, never crash the TUI
        try:
            from requests.exceptions import HTTPError

            from yeaboi.tools.confluence import _confluence_error_msg

            if isinstance(e, HTTPError):
                msg = _confluence_error_msg(e)
            else:
                msg = f"Confluence export failed: {e}"
        except Exception:
            msg = f"Confluence export failed: {e}"
        logger.warning("Confluence export failed for %r: %s", title, e)
        return PublishResult(ok=False, message=msg)


def publish_markdown(destination: str, *, title: str, markdown: str) -> PublishResult:
    """Dispatch a markdown document to the chosen destination ("notion"/"confluence")."""
    if destination == DEST_NOTION:
        return publish_to_notion(title, markdown)
    if destination == DEST_CONFLUENCE:
        return publish_to_confluence(title, markdown)
    logger.warning("Unknown export destination: %r", destination)
    return PublishResult(ok=False, message=f"Unknown export destination: {destination}")
