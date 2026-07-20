"""MCP tools: saved-session reads (sessions_list, session_get)."""

from __future__ import annotations

import logging

from yeaboi.mcp.runtime import run_readonly

logger = logging.getLogger(__name__)


def resolve_session_id(session_id: str = "") -> str:
    """Return `session_id`, or the most recent session when blank."""
    if session_id:
        return session_id
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    with SessionStore(get_db_path()) as store:
        latest = store.get_latest_session_id()
    if not latest:
        raise ValueError("No saved sessions found — generate a plan first (plan_generate) or use the yeaboi TUI.")
    return latest


def _list_sessions() -> list[dict]:
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore, make_display_name

    with SessionStore(get_db_path()) as store:
        rows = store.list_sessions()
    return [
        {
            "session_id": row["session_id"],
            "display_name": make_display_name(row),
            "project_name": row["project_name"],
            "created_at": row["created_at"],
            "last_modified": row["last_modified"],
            "last_node_completed": row["last_node_completed"],
        }
        for row in rows
    ]


def _get_session(session_id: str) -> dict:
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore, make_display_name

    resolved = resolve_session_id(session_id)
    with SessionStore(get_db_path()) as store:
        meta = store.get_session(resolved)
        state = store.load_state(resolved)
    if meta is None:
        raise ValueError(f"Session not found: {resolved}")

    questionnaire = (state or {}).get("questionnaire")
    return {
        "session_id": resolved,
        "display_name": make_display_name(meta),
        "project_name": meta.get("project_name", ""),
        "created_at": meta.get("created_at", ""),
        "last_modified": meta.get("last_modified", ""),
        "last_node_completed": meta.get("last_node_completed", ""),
        "artifacts": {
            "analysis": (state or {}).get("project_analysis") is not None,
            "epics": len((state or {}).get("features") or []),
            "stories": len((state or {}).get("stories") or []),
            "tasks": len((state or {}).get("tasks") or []),
            "sprints": len((state or {}).get("sprints") or []),
        },
        "questionnaire_completed": bool(getattr(questionnaire, "completed", False)),
    }


def _delete_session(session_id: str) -> dict:
    if not session_id.strip():
        raise ValueError("session_id is required — deletion never defaults to the latest session.")
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    with SessionStore(get_db_path()) as store:
        deleted = store.delete_session(session_id.strip())
    if not deleted:
        raise ValueError(f"Session not found: {session_id}")
    return {"session_id": session_id.strip(), "deleted": True}


def _usage_get() -> dict:
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    db_path = get_db_path()
    if not db_path.exists():
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
    else:
        with SessionStore(db_path) as store:
            usage = store.get_lifetime_usage()
    # MCP sampling responses carry no token counts — the host pays for those
    # calls and yeaboi's ledger intentionally skips them.
    usage["note"] = "Sampling-mode LLM calls are billed to the host agent and not counted here."
    return usage


def register(app) -> None:
    """Attach the session tools to the FastMCP app."""

    @app.tool()
    async def sessions_list() -> dict:
        """List saved yeaboi planning sessions (id, project name, dates, progress)."""
        return await run_readonly(_list_sessions)

    @app.tool()
    async def session_get(session_id: str = "") -> dict:
        """Get one session's metadata and artifact counts. Blank session_id = most recent session."""
        return await run_readonly(_get_session, session_id)

    @app.tool()
    async def session_delete(session_id: str) -> dict:
        """Permanently delete one saved session (its plan, standup/retro history links, logs
        pointer). DESTRUCTIVE and irreversible — requires an exact session_id from
        sessions_list and explicit user confirmation; never guess the id."""
        return await run_readonly(_delete_session, session_id)

    @app.tool()
    async def usage_get() -> dict:
        """Get lifetime LLM token usage recorded by yeaboi (input/output tokens, call count)
        across all sessions and modes. Sampling-mode calls (host-billed) are not counted."""
        return await run_readonly(_usage_get)
