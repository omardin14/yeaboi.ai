"""Labels on a run: a project label, tags, and the scope it read under.

One central ``session_labels`` table in sessions.db, keyed by
``(mode, session_id, run_id)`` — the key every store already hands out —
rather than a column in each of nine history tables. The label is about the
run, not part of its artifact, so no report shape changes; autocomplete is
one ``SELECT DISTINCT``; and a row's ``scope_json`` is how a reopened run
shows what it read and how "run it again the same way" works.

Performance runs are keyed ``<kind>:<id>`` (``prep:12``) because three tables
share one mode.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from yeaboi.context.scope import ContextScope

logger = logging.getLogger(__name__)

#: The ``mode`` values a label row may carry.
LABEL_MODES: tuple[str, ...] = (
    "planning",
    "analysis",
    "standup",
    "retro",
    "poker",
    "performance",
    "reporting",
    "review",
)

SESSION_LABELS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS session_labels (
    mode        TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    run_id      TEXT NOT NULL DEFAULT '',
    project     TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    scope_json  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (mode, session_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_session_labels_project ON session_labels(project);
"""

MAX_TAG_LENGTH = 40
_TAG_SPACES = re.compile(r"\s+")
_TAG_STRIP = re.compile(r"[^a-z0-9:\-._/]")


@dataclass(frozen=True)
class SessionLabels:
    """One label row."""

    mode: str
    session_id: str
    run_id: str = ""
    project: str = ""
    tags: tuple[str, ...] = ()
    scope: dict | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "project_label": self.project,
            "tags": list(self.tags),
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def normalize_tag(tag: str) -> str:
    """Lower-case, spaces to ``-``, only ``a-z 0-9 : - . _ /``, at most 40 chars; ``""`` when nothing is left."""
    text = _TAG_SPACES.sub("-", str(tag or "").strip().lower())
    text = _TAG_STRIP.sub("", text).strip("-")
    return text[:MAX_TAG_LENGTH].rstrip("-")


def normalize_tags(tags) -> tuple[str, ...]:
    """Sorted, deduped, normalised; blanks dropped."""
    if isinstance(tags, str):
        tags = tags.split(",")
    return tuple(sorted({normalize_tag(t) for t in (tags or ()) if normalize_tag(t)}))


def default_tags(
    mode: str,
    *,
    today: date,
    world: str = "team",
    sprint_number: int | None = None,
    tracker_key: str = "",
    plan_size: str = "",
    engineer: str = "",
    kind: str = "",
    period: str = "",
    week_label: str = "",
    source: str = "",
    sprint_day: int | None = None,
) -> tuple[str, ...]:
    """The ``key:value`` tags every run gets for free, so they never collide with a free tag."""
    tags = [f"mode:{mode}", f"world:{'solo' if world == 'solo' else 'team'}", today.strftime("%Y-%m")]
    if sprint_number:
        tags.append(f"sprint:{sprint_number}")
    if tracker_key:
        tags.append(f"tracker:{tracker_key}")
    if mode == "planning" and plan_size:
        tags.append(
            f"size:{'small' if plan_size == 'small_project' else 'large' if plan_size == 'smart' else plan_size}"
        )
    if mode == "performance":
        if engineer:
            tags.append(f"engineer:{engineer}")
        if kind:
            tags.append(f"kind:{'1on1' if kind in ('prep', 'completion', '1on1') else kind}")
    if mode == "reporting" and period:
        tags.append(f"period:{period}")
    if mode == "review" and week_label:
        tags.append(f"week:{week_label}")
    if mode == "poker" and source:
        tags.append(f"source:{source}")
    if mode == "standup" and sprint_day:
        tags.append(f"sprint-day:{sprint_day}")
    return normalize_tags(tags)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LabelStore:
    """The ``session_labels`` table. Same shape as the mode stores: autocommit, a context manager."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.isolation_level = None
        self._conn.executescript(SESSION_LABELS_SCHEMA)

    def __enter__(self) -> LabelStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def set_labels(
        self,
        mode: str,
        session_id: str,
        run_id: str = "",
        *,
        project: str | None = None,
        tags=(),
        scope: ContextScope | dict | None = None,
        merge_tags: bool = True,
        clear_scope: bool = False,
    ) -> SessionLabels:
        """Upsert one row.

        ``merge_tags`` keeps the tags already there and adds; ``project`` None
        keeps the old label and ``""`` clears it; a ``None`` scope keeps the
        old one unless ``clear_scope`` says the run reads unscoped now.
        """
        if mode not in LABEL_MODES:
            raise ValueError(f"unknown label mode {mode!r} — one of {', '.join(LABEL_MODES)}")
        if not session_id and not run_id:
            raise ValueError("a label needs a session_id or a run_id")
        existing = self.get_labels(mode, session_id, run_id)
        new_tags = set(normalize_tags(tags))
        if existing and merge_tags:
            new_tags |= set(existing.tags)
        if project is None:
            project = existing.project if existing else ""
        else:
            project = project.strip()
        scope_dict = scope.to_dict() if isinstance(scope, ContextScope) else scope
        if clear_scope:
            scope_json = ""
        elif scope_dict is not None:
            scope_json = json.dumps(scope_dict, sort_keys=True)
        elif existing and existing.scope is not None:
            scope_json = json.dumps(existing.scope, sort_keys=True)
        else:
            scope_json = ""
        now = _now()
        self._conn.execute(
            """INSERT INTO session_labels
                   (mode, session_id, run_id, project, tags_json, scope_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mode, session_id, run_id) DO UPDATE SET
                   project = excluded.project, tags_json = excluded.tags_json,
                   scope_json = excluded.scope_json, updated_at = excluded.updated_at""",
            (mode, session_id, run_id, project, json.dumps(sorted(new_tags)), scope_json, now, now),
        )
        logger.info("labels: %s/%s/%s project=%r tags=%d", mode, session_id, run_id or "-", project, len(new_tags))
        return self.get_labels(mode, session_id, run_id) or SessionLabels(mode, session_id, run_id)

    def get_labels(self, mode: str, session_id: str, run_id: str = "") -> SessionLabels | None:
        row = self._conn.execute(
            "SELECT mode, session_id, run_id, project, tags_json, scope_json, created_at, updated_at "
            "FROM session_labels WHERE mode = ? AND session_id = ? AND run_id = ?",
            (mode, session_id, run_id),
        ).fetchone()
        return self._row(row) if row else None

    def list_labels(self, *, mode: str = "", project: str = "", tags=(), limit: int = 100) -> list[SessionLabels]:
        """Rows newest first, narrowed by mode, project label and required tags."""
        rows = self._conn.execute(
            "SELECT mode, session_id, run_id, project, tags_json, scope_json, created_at, updated_at "
            "FROM session_labels WHERE (? = '' OR mode = ?) ORDER BY updated_at DESC",
            (mode, mode),
        ).fetchall()
        wanted = set(normalize_tags(tags))
        out = [self._row(r) for r in rows]
        wanted_project = project.strip().casefold()
        if wanted_project:
            out = [r for r in out if r.project.strip().casefold() == wanted_project]
        if wanted:
            out = [r for r in out if wanted <= set(r.tags)]
        return out[:limit] if limit > 0 else out

    def find_ids(self, mode: str, *, projects=(), tags=()) -> set[str]:
        """The ids under ``mode`` carrying any of ``projects`` and all of ``tags``.

        An id is the ``run_id`` when set, else the ``session_id``.
        """
        rows = self._conn.execute(
            "SELECT session_id, run_id, project, tags_json FROM session_labels WHERE mode = ?", (mode,)
        ).fetchall()
        wanted_projects = {p.strip().casefold() for p in projects if p.strip()}
        wanted_tags = set(normalize_tags(tags))
        found: set[str] = set()
        for session_id, run_id, project, tags_json in rows:
            if wanted_projects and (project or "").strip().casefold() not in wanted_projects:
                continue
            if wanted_tags and not wanted_tags <= set(_tags(tags_json)):
                continue
            found.add(run_id or session_id)
        return found

    def list_projects(self, prefix: str = "", limit: int = 50) -> list[str]:
        """Distinct project labels, most recently used first."""
        rows = self._conn.execute(
            "SELECT project, MAX(updated_at) AS used FROM session_labels WHERE project != '' "
            "GROUP BY project ORDER BY used DESC"
        ).fetchall()
        needle = prefix.strip().lower()
        labels = [r[0] for r in rows if not needle or r[0].lower().startswith(needle)]
        return labels[:limit] if limit > 0 else labels

    def list_tags(self, prefix: str = "", limit: int = 100) -> list[tuple[str, int]]:
        """``(tag, count)`` pairs, most used first."""
        counts: dict[str, int] = {}
        for (tags_json,) in self._conn.execute("SELECT tags_json FROM session_labels").fetchall():
            for tag in _tags(tags_json):
                counts[tag] = counts.get(tag, 0) + 1
        needle = normalize_tag(prefix)
        pairs = sorted(
            ((tag, n) for tag, n in counts.items() if not needle or tag.startswith(needle)),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return pairs[:limit] if limit > 0 else pairs

    def delete(self, mode: str, session_id: str = "", run_id: str = "") -> bool:
        """Drop the rows for a session (every run) or one run. Returns whether anything went."""
        if not session_id and not run_id:
            raise ValueError("delete needs a session_id or a run_id")
        if session_id and run_id:
            cursor = self._conn.execute(
                "DELETE FROM session_labels WHERE mode = ? AND session_id = ? AND run_id = ?",
                (mode, session_id, run_id),
            )
        elif run_id:
            cursor = self._conn.execute("DELETE FROM session_labels WHERE mode = ? AND run_id = ?", (mode, run_id))
        else:
            cursor = self._conn.execute(
                "DELETE FROM session_labels WHERE mode = ? AND session_id = ?", (mode, session_id)
            )
        return (cursor.rowcount or 0) > 0

    @staticmethod
    def _row(row) -> SessionLabels:
        scope = None
        if row[5]:
            try:
                scope = json.loads(row[5])
            except (json.JSONDecodeError, TypeError):
                scope = None
        return SessionLabels(
            mode=row[0],
            session_id=row[1],
            run_id=row[2],
            project=row[3] or "",
            tags=tuple(_tags(row[4])),
            scope=scope if isinstance(scope, dict) else None,
            created_at=row[6],
            updated_at=row[7],
        )


def _tags(tags_json: str) -> list[str]:
    try:
        parsed = json.loads(tags_json) if tags_json else []
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(t) for t in parsed] if isinstance(parsed, list) else []


def drop_run_labels(db_path: Path, mode: str, run_id: int | str) -> None:
    """Best-effort: a store deleting a run drops its label row too. Never raises."""
    try:
        with LabelStore(db_path) as store:
            store.delete(mode, run_id=str(run_id))
    except Exception:  # noqa: BLE001 — a label left behind is not worth failing a delete
        logger.debug("drop_run_labels failed for %s/%s", mode, run_id, exc_info=True)


def label_run(
    mode: str,
    session_id: str,
    run_id: int | str = "",
    *,
    project_label: str = "",
    tags=(),
    scope: ContextScope | dict | None = None,
    defaults: dict | None = None,
    db_path: Path | None = None,
    today: date | None = None,
) -> SessionLabels | None:
    """The write side every engine calls at record time. Never raises.

    ``defaults`` are the :func:`default_tags` keyword facts the run knows
    (``sprint_number``, ``engineer``, ``period`` …); the user's ``tags`` are
    merged on top. A label failure is logged, never raised — it must not
    fail the run it describes.
    """
    try:
        from yeaboi.paths import get_db_path

        facts = dict(defaults or {})
        facts.setdefault("today", today or date.today())
        merged = (*default_tags(mode, **facts), *normalize_tags(tags))
        with LabelStore(db_path or get_db_path()) as store:
            return store.set_labels(
                mode,
                session_id,
                str(run_id or ""),
                project=project_label or None,
                tags=merged,
                scope=scope,
                clear_scope=scope is None,
            )
    except Exception:  # noqa: BLE001 — a missing label must not fail the run it describes
        logger.warning("label_run failed for %s/%s/%s (non-fatal)", mode, session_id, run_id, exc_info=True)
        return None
