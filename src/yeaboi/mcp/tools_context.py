"""MCP tools: the context scope a run reads under, and the labels runs carry."""

from __future__ import annotations

import logging

from yeaboi.mcp.runtime import run_readonly

logger = logging.getLogger(__name__)


def _context_options(mode: str) -> dict:
    from dataclasses import asdict

    from yeaboi.context.engine import context_options

    return asdict(context_options(mode=mode))


def _context_preview(context, mode: str, rows: bool) -> dict:
    from yeaboi.context.engine import preview_scope

    result = preview_scope(context, mode=mode, rows=rows)
    selection = result.selection
    return {
        "scope": selection.scope.to_dict() if selection.scope is not None else None,
        "window": {"start": selection.start, "end": selection.end},
        "summary": result.label,
        "counts": dict(result.counts),
        "rows": {key: [r.__dict__ for r in found] for key, found in result.rows.items()},
        "warnings": list(selection.warnings),
    }


def _labels_get(mode: str, session_id: str, run_id: str) -> dict:
    from yeaboi.context.engine import get_session_labels

    row = get_session_labels(mode, session_id, run_id)
    if row is None:
        raise ValueError(f"no labels for {mode} {session_id!r}")
    return row.to_dict()


def _labels_set(
    mode: str, session_id: str, run_id: str, project_label: str | None, tags: list | None, merge_tags: bool
) -> dict:
    from yeaboi.context.engine import set_session_labels

    return set_session_labels(
        mode, session_id, run_id, project_label=project_label, tags=tags or (), merge_tags=merge_tags
    ).to_dict()


def _labels_list(mode: str, project_label: str, tags: list | None, limit: int) -> dict:
    from yeaboi.context.engine import list_session_labels

    rows = list_session_labels(mode=mode, project_label=project_label, tags=tags or (), limit=limit)
    return {"labels": [row.to_dict() for row in rows]}


def register(app) -> None:
    """Attach the context tools to the FastMCP app."""

    @app.tool()
    async def context_options(mode: str = "") -> dict:
        """What a run may read from other sessions: the sources with how many runs each has, the
        window kinds (everything / last N sprints / month / quarter / year / custom), the project
        labels and tags in use, the sprint calendar in force and where it came from, the mode's
        remembered scope, and the default tags a run of `mode` gets. Call this before building a
        `context` spec for any run tool."""
        return await run_readonly(_context_options, mode)

    @app.tool()
    async def context_preview(context: str | dict | None = None, mode: str = "", rows: bool = False) -> dict:
        """What a `context` spec would read, before running anything: counts per source, the
        resolved date window and a one-line summary ("12 standups · 2 retros · 4 Aug – 11 Sep").
        `context` is 'all', 'none', or a spec like 'standup,retro:1@2sprints project=apollo
        tags=q3' (a JSON object of the same shape is accepted); `rows` also lists the matching
        runs. Use it when the user names a timeframe, then pass the same `context` to the run."""
        return await run_readonly(_context_preview, context, mode, rows)

    @app.tool()
    async def session_labels_get(mode: str, session_id: str, run_id: str = "") -> dict:
        """The project label, tags and scope one run carries. `mode` is planning, analysis,
        standup, retro, poker, performance, reporting or review; `run_id` is the store's own
        row id for the history modes (blank for a planning or analysis session)."""
        return await run_readonly(_labels_get, mode, session_id, run_id)

    @app.tool()
    async def session_labels_set(
        mode: str,
        session_id: str,
        run_id: str = "",
        project_label: str | None = None,
        tags: list[str] | None = None,
        merge_tags: bool = True,
    ) -> dict:
        """Label a run after the fact: set its free-text project label (omit to keep it, "" to
        clear it) and add tags (the run's default `key:value` tags stay); merge_tags=false
        replaces the tags instead. Same ids as session_labels_get."""
        return await run_readonly(_labels_set, mode, session_id, run_id, project_label, tags, merge_tags)

    @app.tool()
    async def session_labels_list(
        mode: str = "", project_label: str = "", tags: list[str] | None = None, limit: int = 100
    ) -> dict:
        """The runs carrying labels, newest first — narrowed by mode, by project label and by
        the tags they must all carry. The way to answer "what have we run for project X"."""
        return await run_readonly(_labels_list, mode, project_label, tags, limit)
