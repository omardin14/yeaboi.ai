"""Native routes for the context scope and the labels a run carries.

Three reads and one write over :mod:`yeaboi.context.engine`: the options a
picker draws, a preview of what a scope would read, and a run's labels.
The run routes themselves take the scope in their bodies (see
``app/_context_body.py``); this module is what a picker talks to before a run.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from yeaboi.app._context_body import read_context
from yeaboi.app.router import HTTPError, Request, Response, json_response
from yeaboi.context.labels import LABEL_MODES

logger = logging.getLogger(__name__)


def options(app, request: Request) -> Response:
    """``GET /api/context/options?mode=`` — sources with counts, labels, windows, the sprint calendar."""
    from yeaboi.context.engine import context_options

    mode = str(request.query.get("mode", "")).strip()
    try:
        result = context_options(mode=mode)
    except ValueError as exc:
        raise HTTPError(400, str(exc)) from None
    return json_response(asdict(result))


def preview(app, request: Request) -> Response:
    """``POST /api/context/preview`` — ``{context, mode?, rows?}`` → what the scope would read."""
    from yeaboi.context.engine import preview_scope
    from yeaboi.context.window import window_label

    payload = request.json()
    scope, _label, _tags = read_context(payload)
    mode = str(payload.get("mode", "")).strip()
    if mode and mode not in LABEL_MODES:
        raise HTTPError(400, f"unknown mode {mode!r} — one of {', '.join(LABEL_MODES)}")
    rows = bool(payload.get("rows", False))
    result = preview_scope(scope, mode=mode, rows=rows)
    selection = result.selection
    sources = [
        {
            "key": key,
            "count": count,
            "rows": [
                {
                    "session_id": row.session_id,
                    "run_id": row.run_id,
                    "title": row.title,
                    "date": row.on_date,
                    "project_label": row.project,
                    "tags": list(row.tags),
                }
                for row in result.rows.get(key, ())
            ],
        }
        for key, count in result.counts.items()
    ]
    return json_response(
        {
            "scope": selection.scope.to_dict() if selection.scope is not None else None,
            "window": {
                "start": selection.start,
                "end": selection.end,
                "label": window_label(selection.start, selection.end),
            },
            "summary": result.label,
            "sources": sources,
            "warnings": list(selection.warnings),
        }
    )


def labels_get(app, request: Request) -> Response:
    """``GET /api/sessions/{mode}/{session_id}/labels?run_id=`` — one run's labels; 404 when it has none."""
    from yeaboi.context.engine import get_session_labels

    mode, session_id = _mode_and_id(request)
    run_id = str(request.query.get("run_id", "")).strip()
    row = get_session_labels(mode, session_id, run_id)
    if row is None:
        raise HTTPError(404, f"no labels for {mode} {session_id!r}")
    return json_response(row.to_dict())


def labels_set(app, request: Request) -> Response:
    """``POST /api/sessions/{mode}/{session_id}/labels`` — ``{run_id?, project_label?, tags?, merge_tags?}``."""
    from yeaboi.context.engine import set_session_labels

    mode, session_id = _mode_and_id(request)
    payload = request.json()
    _scope, project_label, tags = read_context(payload)
    run_id = str(payload.get("run_id", "") or "").strip()
    merge_tags = bool(payload.get("merge_tags", True))
    try:
        row = set_session_labels(
            mode, session_id, run_id, project_label=project_label, tags=tags, merge_tags=merge_tags
        )
    except ValueError as exc:
        raise HTTPError(400, str(exc)) from None
    logger.info("labels set over http: %s/%s/%s", mode, session_id, run_id or "-")
    return json_response(row.to_dict())


def _mode_and_id(request: Request) -> tuple[str, str]:
    mode = request.params.get("mode", "")
    session_id = request.params.get("session_id", "")
    if mode not in LABEL_MODES:
        raise HTTPError(400, f"unknown mode {mode!r} — one of {', '.join(LABEL_MODES)}")
    if not session_id:
        raise HTTPError(400, "session_id is required")
    return mode, session_id
