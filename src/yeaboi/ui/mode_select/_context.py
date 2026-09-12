"""The context page: what a run reads from other sessions, chosen before it starts.

Every hub's "+ New" card and the planning intake open this page. It edits a
:class:`ContextDraft` — the sources as chips, the window, the project labels
and tags — shows what that draft would read, and hands back a
:class:`ContextScope` on Use. The caller persists it as the mode's remembered
scope, which is the value every engine falls back to when a run passes no
``context`` of its own (see ``context.resolve.selection_for``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from rich.console import Console

from yeaboi.context.labels import normalize_tags
from yeaboi.context.scope import SOURCES, WINDOW_KINDS, ContextScope, Window

logger = logging.getLogger(__name__)

CONTEXT_ACTIONS = ["Use", "All on", "Incognito", "Back"]

#: The rows below the source chips, in order. ``from``/``to`` appear only for a custom window.
_WINDOW_ROW = "window"
_TEXT_ROWS = ("from", "to", "project", "tags")


@dataclass
class ContextDraft:
    """The page's editing state — a scope taken apart into fields a key loop can move through."""

    sources: set[str] | None = None  # None = every source; empty = incognito
    window_kind: str = "all"
    count: int = 1
    start: str = ""
    end: str = ""
    project: str = ""  # comma-separated labels
    tags: str = ""  # comma-separated tags
    message: str = ""

    @classmethod
    def from_scope(cls, scope: ContextScope | None) -> ContextDraft:
        if scope is None:
            return cls()
        return cls(
            sources=None if scope.sources is None else set(scope.sources),
            window_kind=scope.window.kind,
            count=max(1, scope.window.count),
            start=scope.window.start,
            end=scope.window.end,
            project=", ".join(scope.projects),
            tags=", ".join(scope.tags),
        )

    def rows(self) -> list[str]:
        """Row keys top to bottom: one per source, then the window and the text fields."""
        rows = [f"src:{name}" for name in SOURCES] + [_WINDOW_ROW]
        if self.window_kind == "custom":
            rows += ["from", "to"]
        return rows + ["project", "tags"]

    def is_on(self, source: str) -> bool:
        return self.sources is None or source in self.sources

    def toggle(self, source: str) -> None:
        # Inherit materialises to the full set on the first toggle, so switching
        # one source off leaves the others explicitly on.
        current = set(SOURCES) if self.sources is None else set(self.sources)
        current.symmetric_difference_update({source})
        self.sources = current

    def cycle_window(self, step: int) -> None:
        idx = WINDOW_KINDS.index(self.window_kind)
        self.window_kind = WINDOW_KINDS[(idx + step) % len(WINDOW_KINDS)]

    def text(self, row: str) -> str:
        return {"from": self.start, "to": self.end, "project": self.project, "tags": self.tags}[row]

    def set_text(self, row: str, value: str) -> None:
        if row == "from":
            self.start = value
        elif row == "to":
            self.end = value
        elif row == "project":
            self.project = value
        else:
            self.tags = value

    def to_scope(self) -> ContextScope:
        """The draft as a scope. Raises ``ValueError`` for a malformed custom date."""
        window = Window(
            kind=self.window_kind,
            count=self.count if self.window_kind == "sprints" else 0,
            start=self.start.strip() if self.window_kind == "custom" else "",
            end=self.end.strip() if self.window_kind == "custom" else "",
        )
        return ContextScope(
            sources=None if self.sources is None else frozenset(self.sources),
            window=window,
            projects=tuple(p.strip() for p in self.project.split(",") if p.strip()),
            tags=normalize_tags(self.tags),
        )


@dataclass
class ContextPreview:
    """What the page shows under the fields: per-source counts and the one-line summary."""

    counts: dict[str, int] = field(default_factory=dict)
    label: str = ""
    calendar_source: str = ""


def preview_draft(draft: ContextDraft, db_path=None) -> ContextPreview:
    """Read the stores for ``draft``; a malformed draft or a failing read is a blank preview."""
    from yeaboi.context.resolve import preview_scope

    try:
        preview = preview_scope(draft.to_scope(), db_path=db_path)
    except ValueError as exc:
        return ContextPreview(label=str(exc))
    return ContextPreview(
        counts=dict(preview.counts), label=preview.label, calendar_source=preview.selection.calendar_source
    )


def complete_text(row: str, value: str, db_path=None) -> str:
    """Tab on a text row: the first known label or tag that starts with the last token."""
    if row not in ("project", "tags") or db_path is None:
        return value
    from yeaboi.context.labels import LabelStore

    head, _sep, tail = value.rpartition(",")
    prefix = tail.strip()
    try:
        with LabelStore(db_path) as store:
            if row == "project":
                found = store.list_projects(prefix, limit=1)
            else:
                found = [tag for tag, _n in store.list_tags(prefix, limit=1)]
    except Exception:  # noqa: BLE001 — autocomplete is a convenience, never a failure
        logger.debug("context page: autocomplete failed", exc_info=True)
        return value
    if not found:
        return value
    return f"{head}, {found[0]}" if head else found[0]


def run_context_page(
    console: Console,
    live,
    read_key,
    frame_time: float,
    supports_timeout: bool,
    *,
    mode: str,
    initial: ContextScope | None = None,
    theme=None,
    title_fn=None,
    db_path=None,
) -> ContextScope | None:
    """Edit what a ``mode`` run reads. Returns the chosen scope on Use, ``None`` on Back or Esc.

    Space toggles the focused source; ←/→ cycle the window kind on its row (and
    move the buttons elsewhere); ``+``/``-`` change a sprint count; typing edits
    the focused text field and Tab completes it from the labels in use.
    """
    from yeaboi.ui.mode_select.screens._screens_context import _build_context_screen

    draft = ContextDraft.from_scope(initial)
    selected = 0
    action_sel = 0
    dirty = True
    preview = ContextPreview()
    start = time.monotonic()
    logger.info("context page opened: mode=%s initial=%s", mode, initial.to_spec() if initial else "-")

    while True:
        if dirty:
            preview = preview_draft(draft, db_path=db_path)
            dirty = False
        rows = draft.rows()
        selected = min(selected, len(rows) - 1)
        row = rows[selected]
        w, h = console.size
        live.update(
            _build_context_screen(
                draft,
                preview,
                selected=selected,
                action_sel=action_sel,
                width=w,
                height=h,
                shimmer_tick=time.monotonic() - start,
                sub_reveal=(time.monotonic() - start) * 6.0,
                theme=theme,
                title_fn=title_fn,
                mode=mode,
            )
        )
        key = read_key(timeout=frame_time) if supports_timeout else read_key()
        on_text = row in _TEXT_ROWS

        if key == "esc" or (key == "q" and not on_text):
            logger.info("context page closed: mode=%s unchanged", mode)
            return None
        if key in ("up", "down"):
            selected = (selected + (1 if key == "down" else -1)) % len(rows)
            draft.message = ""
        elif key in ("left", "right") and row == _WINDOW_ROW:
            draft.cycle_window(1 if key == "right" else -1)
            dirty = True
        elif key in ("left", "right"):
            action_sel = (action_sel + (1 if key == "right" else -1)) % len(CONTEXT_ACTIONS)
        elif key in ("+", "=", "-", "_") and row == _WINDOW_ROW and draft.window_kind == "sprints":
            draft.count = max(1, draft.count + (1 if key in ("+", "=") else -1))
            dirty = True
        elif key == " " and row.startswith("src:"):
            draft.toggle(row[4:])
            draft.message = ""
            dirty = True
        elif key == "enter":
            choice = CONTEXT_ACTIONS[action_sel]
            if choice == "Back":
                logger.info("context page closed from the buttons: mode=%s unchanged", mode)
                return None
            if choice == "All on":
                draft.sources = None
                draft.message = "Every source on."
                dirty = True
            elif choice == "Incognito":
                draft.sources = set()
                draft.message = "Incognito — this run reads no other session. It is still saved."
                dirty = True
            elif choice == "Use":
                try:
                    scope = draft.to_scope()
                except ValueError as exc:
                    draft.message = str(exc)
                    continue
                logger.info("context page: mode=%s uses %s", mode, scope.to_spec())
                return scope
        elif on_text and key == "backspace":
            draft.set_text(row, draft.text(row)[:-1])
            dirty = True
        elif on_text and key == "tab":
            draft.set_text(row, complete_text(row, draft.text(row), db_path=db_path))
            dirty = True
        elif on_text and isinstance(key, str) and len(key) == 1 and key.isprintable():
            draft.set_text(row, draft.text(row) + key)
            dirty = True
