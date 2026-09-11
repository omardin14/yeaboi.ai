"""Native routes for the cross-mode sessions list and the composer's @ picker.

Two reads no engine owns: the union of every mode's saved runs
(``sessions_recent``), which is what a Sessions page lists, and one connected
source's rows for the reference picker (``references``).
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from yeaboi.app.router import HTTPError, Request, Response, json_response

logger = logging.getLogger(__name__)


def recent(app, request: Request) -> Response:
    """``GET /api/sessions/recent?limit=&mode=&project_label=`` — the newest runs across every mode.

    ``project_id`` is the name an older window sends for the label; it means the same thing.
    """
    from yeaboi.sessions_recent import recent_sessions

    mode = str(request.query.get("mode", "")).strip()
    project_label = " ".join(str(request.query.get("project_label") or request.query.get("project_id") or "").split())
    raw_limit = str(request.query.get("limit", "")).strip()
    try:
        limit = int(raw_limit) if raw_limit else 20
    except ValueError:
        raise HTTPError(400, "limit must be a number") from None
    if limit < 0:
        raise HTTPError(400, "limit must be zero or more")
    try:
        rows = recent_sessions(limit=limit, mode=mode, project_label=project_label)
    except ValueError as exc:
        raise HTTPError(400, str(exc)) from None
    return json_response({"sessions": [asdict(row) for row in rows]})


def references(app, request: Request) -> Response:
    """``GET /api/references?source=&q=&limit=`` — one source's rows for the @ picker; 400 when malformed."""
    from yeaboi.mcp.runtime import to_jsonable
    from yeaboi.references import DEFAULT_LIMIT, MAX_LIMIT, SOURCES

    source = str(request.query.get("source", "")).strip().lower()
    if source not in SOURCES:
        raise HTTPError(400, f"source must be one of {', '.join(SOURCES)}")
    q = " ".join(str(request.query.get("q", "")).split())[:200]
    raw_limit = str(request.query.get("limit", "")).strip()
    try:
        limit = int(raw_limit) if raw_limit else DEFAULT_LIMIT
    except ValueError:
        raise HTTPError(400, "limit must be a number") from None
    sheet = app.references.get(source, q, limit=max(1, min(limit, MAX_LIMIT)))
    logger.info(
        "references requested: %s q=%r -> %d row(s)%s",
        source,
        q,
        len(sheet.items),
        " (could not be read)" if sheet.warning else "",
    )
    return json_response(to_jsonable(sheet))
