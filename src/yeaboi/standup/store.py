"""SQLite store for the Daily Standup mode.

Persists three things in the shared ~/.scrum-agent/sessions.db:
- ``standup_config``  — per-session schedule + delivery preferences
- ``standup_history`` — every run's serialized StandupReport + delivery status
- ``standup_updates`` — user-typed "my update" text, consumed verbatim by the engine

Follows the exact patterns used by TeamProfileStore (team_profile.py): a separate
store class opening its own connection to the same DB, autocommit mode, context
manager support, idempotent CREATE-IF-NOT-EXISTS schema. The schema constant is
also referenced by sessions.py's v6 migration so an existing DB gets the tables.

# See README: "Session Management" — SQLite persistence, schema versioning
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from yeaboi.agent.state import MemberUpdate, StandupReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema — referenced by sessions.py migration v6 AND created on store open
# ---------------------------------------------------------------------------

_STANDUP_SCHEMA = """\
CREATE TABLE IF NOT EXISTS standup_config (
    session_id        TEXT PRIMARY KEY,
    enabled           INTEGER NOT NULL DEFAULT 0,
    time              TEXT NOT NULL DEFAULT '10:00',
    lead_minutes      INTEGER NOT NULL DEFAULT 10,
    timezone          TEXT NOT NULL DEFAULT '',
    weekdays          TEXT NOT NULL DEFAULT '1-5',
    delivery_channels TEXT NOT NULL DEFAULT '["terminal"]',
    repo_path         TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS standup_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    run_at          TEXT NOT NULL,
    standup_date    TEXT NOT NULL DEFAULT '',
    sprint_day      INTEGER NOT NULL DEFAULT 0,
    confidence_pct  INTEGER NOT NULL DEFAULT 0,
    report_json     TEXT NOT NULL DEFAULT '',
    delivery_status TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'success',
    error           TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS standup_updates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    standup_date TEXT NOT NULL,
    member       TEXT NOT NULL,
    update_text  TEXT NOT NULL DEFAULT '',
    images_json  TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL
);"""


# ---------------------------------------------------------------------------
# Serialisation helpers — StandupReport <-> JSON (same pattern as sessions.py)
# ---------------------------------------------------------------------------


def _standup_report_to_json(report: StandupReport) -> str:
    """Serialize a StandupReport to a JSON string.

    ``asdict`` recursively turns the frozen MemberUpdate tuples into dicts and
    the activity_counts tuple-of-tuples into nested lists; both are rebuilt with
    the correct types by ``_dict_to_standup_report``.
    """
    return json.dumps(asdict(report), ensure_ascii=False)


def _dict_to_standup_report(d: dict) -> StandupReport:
    """Reconstruct a StandupReport from a JSON-parsed dict.

    Uses ``.get()`` with defaults for every field so reports serialized by an
    older version (missing keys) still deserialize — see CLAUDE.md
    "Frozen dataclass backward compatibility".
    """
    members = tuple(
        MemberUpdate(
            name=m.get("name", ""),
            summary=m.get("summary", ""),
            blockers=m.get("blockers", ""),
            source=m.get("source", "inferred"),
        )
        for m in d.get("member_updates", ())
    )
    # JSON turned each (source, count) tuple into a [source, count] list — rebuild tuples.
    counts = tuple((str(c[0]), int(c[1])) for c in d.get("activity_counts", ()) if len(c) == 2)
    return StandupReport(
        date=d.get("date", ""),
        session_id=d.get("session_id", ""),
        sprint_name=d.get("sprint_name", ""),
        sprint_day=d.get("sprint_day", 0),
        sprint_total_days=d.get("sprint_total_days", 0),
        confidence_pct=d.get("confidence_pct", 0),
        confidence_label=d.get("confidence_label", ""),
        confidence_rationale=d.get("confidence_rationale", ""),
        team_summary=d.get("team_summary", ""),
        member_updates=members,
        activity_counts=counts,
        warnings=tuple(d.get("warnings", ())),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class StandupStore:
    """SQLite-backed store for standup config, run history, and self-updates.

    Uses the same database as SessionStore (sessions.db) with dedicated standup
    tables. Follows the same patterns: autocommit mode, context-manager support,
    explicit close.

    # See README: "Session Management" — SQLite persistence
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.isolation_level = None  # autocommit
        self._conn.executescript(_STANDUP_SCHEMA)
        # Idempotent migration: add lead_minutes to standup_config tables created
        # before it existed (same try/except pattern SessionStore uses).
        try:
            self._conn.execute("ALTER TABLE standup_config ADD COLUMN lead_minutes INTEGER NOT NULL DEFAULT 10")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Idempotent migration: screenshots pasted (Ctrl+V) into "My Update" — a
        # JSON list of file paths under ~/.yeaboi/attachments/, attached to the
        # summary LLM call as multimodal image blocks at run time.
        try:
            self._conn.execute("ALTER TABLE standup_updates ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # column already exists

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> StandupStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    # ── Config ────────────────────────────────────────────────────────────

    def save_config(
        self,
        session_id: str,
        *,
        enabled: bool,
        time: str,
        weekdays: str,
        delivery_channels: list[str],
        lead_minutes: int = 10,
        timezone: str = "",
        repo_path: str = "",
    ) -> None:
        """Insert or update the standup schedule/delivery config for a session.

        ``time`` is the STANDUP time (e.g. "10:00"); the scheduler fires
        ``lead_minutes`` earlier.
        """
        now = self._now()
        channels_json = json.dumps(delivery_channels)
        logger.info(
            "Saving standup config: session=%s enabled=%s standup_time=%s lead=%d channels=%s",
            session_id,
            enabled,
            time,
            lead_minutes,
            delivery_channels,
        )
        self._conn.execute(
            """INSERT INTO standup_config
                   (session_id, enabled, time, lead_minutes, timezone, weekdays, delivery_channels,
                    repo_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   enabled = excluded.enabled,
                   time = excluded.time,
                   lead_minutes = excluded.lead_minutes,
                   timezone = excluded.timezone,
                   weekdays = excluded.weekdays,
                   delivery_channels = excluded.delivery_channels,
                   repo_path = excluded.repo_path,
                   updated_at = excluded.updated_at""",
            (session_id, int(enabled), time, int(lead_minutes), timezone, weekdays, channels_json, repo_path, now, now),
        )

    def load_config(self, session_id: str) -> dict | None:
        """Return the standup config for a session as a dict, or None if unset."""
        row = self._conn.execute(
            "SELECT session_id, enabled, time, timezone, weekdays, delivery_channels, repo_path, lead_minutes "
            "FROM standup_config WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            channels = json.loads(row[5]) if row[5] else ["terminal"]
        except (json.JSONDecodeError, TypeError):
            channels = ["terminal"]
        return {
            "session_id": row[0],
            "enabled": bool(row[1]),
            "time": row[2],
            "timezone": row[3],
            "weekdays": row[4],
            "delivery_channels": channels,
            "repo_path": row[6],
            "lead_minutes": row[7] if row[7] is not None else 10,
        }

    # ── Self-reported updates ─────────────────────────────────────────────

    def save_my_update(
        self, session_id: str, standup_date: str, member: str, update_text: str, images: list[str] | None = None
    ) -> None:
        """Store a user-typed update for a member on a given date.

        A member submitting again for the same date overwrites the prior entry
        (delete-then-insert) so the latest text always wins.

        images: file paths of screenshots pasted into the update (Ctrl+V) —
            attached to the summary LLM call when the standup runs.
        """
        logger.info(
            "Saving self-reported update: session=%s date=%s member=%s images=%d",
            session_id,
            standup_date,
            member,
            len(images or []),
        )
        self._conn.execute(
            "DELETE FROM standup_updates WHERE session_id = ? AND standup_date = ? AND member = ?",
            (session_id, standup_date, member),
        )
        self._conn.execute(
            """INSERT INTO standup_updates (session_id, standup_date, member, update_text, images_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, standup_date, member, update_text, json.dumps(images or []), self._now()),
        )

    def get_my_updates(self, session_id: str, standup_date: str) -> dict[str, str]:
        """Return ``{member: update_text}`` for all self-reported updates on a date."""
        rows = self._conn.execute(
            "SELECT member, update_text FROM standup_updates WHERE session_id = ? AND standup_date = ?",
            (session_id, standup_date),
        ).fetchall()
        return {member: text for member, text in rows}

    def get_my_update_images(self, session_id: str, standup_date: str) -> dict[str, list[str]]:
        """Return ``{member: [image paths]}`` for self-reported updates on a date.

        Paths whose file no longer exists are pruned here so the engine only ever
        sees attachable screenshots (deleted files degrade silently).
        """
        rows = self._conn.execute(
            "SELECT member, images_json FROM standup_updates WHERE session_id = ? AND standup_date = ?",
            (session_id, standup_date),
        ).fetchall()
        out: dict[str, list[str]] = {}
        for member, images_json in rows:
            try:
                paths = json.loads(images_json) if images_json else []
            except (json.JSONDecodeError, TypeError):
                paths = []
            live = [p for p in paths if isinstance(p, str) and Path(p).exists()]
            if len(live) < len(paths):
                logger.warning("standup: %d pasted image(s) missing on disk for %s", len(paths) - len(live), member)
            if live:
                out[member] = live
        return out

    # ── Run history ───────────────────────────────────────────────────────

    def record_run(
        self,
        report: StandupReport,
        *,
        delivery_status: dict[str, bool] | None = None,
        status: str = "success",
        error: str = "",
    ) -> int:
        """Persist a completed standup run and return its history row id."""
        report_json = _standup_report_to_json(report)
        cursor = self._conn.execute(
            """INSERT INTO standup_history
                   (session_id, run_at, standup_date, sprint_day, confidence_pct,
                    report_json, delivery_status, status, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.session_id,
                self._now(),
                report.date,
                report.sprint_day,
                report.confidence_pct,
                report_json,
                json.dumps(delivery_status or {}),
                status,
                error,
            ),
        )
        logger.info("Recorded standup run: session=%s date=%s status=%s", report.session_id, report.date, status)
        return int(cursor.lastrowid or 0)

    def get_latest_report(self, session_id: str) -> StandupReport | None:
        """Return the most recent StandupReport for a session, or None."""
        row = self._conn.execute(
            "SELECT report_json FROM standup_history WHERE session_id = ? ORDER BY run_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None or not row[0]:
            return None
        try:
            return _dict_to_standup_report(json.loads(row[0]))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to deserialize standup report for %s: %s", session_id, exc)
            return None

    def get_history(self, session_id: str, limit: int = 30) -> list[dict]:
        """Return recent run metadata (newest first) for a session."""
        rows = self._conn.execute(
            "SELECT run_at, standup_date, sprint_day, confidence_pct, status "
            "FROM standup_history WHERE session_id = ? ORDER BY run_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [
            {
                "run_at": r[0],
                "standup_date": r[1],
                "sprint_day": r[2],
                "confidence_pct": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    # ── Team-wide (cross-session) reads — used by ceremony_history to feed
    #    Planning / Analysis with the team's recent standups. standup_history has
    #    no project_name column, so these are recency-based (team-wide).

    def get_recent_reports(self, limit: int = 10) -> list[StandupReport]:
        """Return recent StandupReports across ALL sessions, newest first."""
        rows = self._conn.execute(
            "SELECT report_json FROM standup_history WHERE status = 'success' ORDER BY run_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        reports: list[StandupReport] = []
        for row in rows:
            if not row[0]:
                continue
            try:
                reports.append(_dict_to_standup_report(json.loads(row[0])))
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning("Failed to deserialize a standup report: %s", exc)
        return reports

    def get_all_history(self, limit: int = 100) -> list[dict]:
        """Return recent standup run metadata across ALL sessions (for cadence)."""
        rows = self._conn.execute(
            "SELECT run_at, standup_date, sprint_day, confidence_pct, status "
            "FROM standup_history ORDER BY run_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"run_at": r[0], "standup_date": r[1], "sprint_day": r[2], "confidence_pct": r[3], "status": r[4]}
            for r in rows
        ]
