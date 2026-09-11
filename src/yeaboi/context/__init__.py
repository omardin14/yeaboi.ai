"""Context scope — what a run may read from other sessions, and the labels runs carry.

Pure vocabulary and grammar in :mod:`.scope`, the sprint calendar in
:mod:`.window`, the label store in :mod:`.labels`, the resolver in
:mod:`.resolve`, and the two common cross-mode reads in :mod:`.reads`.
"""

from yeaboi.context.labels import (
    LabelStore,
    SessionLabels,
    default_tags,
    drop_run_labels,
    normalize_tag,
    normalize_tags,
)
from yeaboi.context.reads import latest_planning_state, recent_standup_blockers
from yeaboi.context.resolve import Preview, Selection, SourceRow, preview_scope, resolve_scope
from yeaboi.context.scope import (
    SOURCE_LABELS,
    SOURCES,
    WINDOW_KINDS,
    ContextScope,
    Window,
    coerce_scope,
    incognito,
    parse_context_spec,
    wants,
)
from yeaboi.context.window import SprintCalendar, load_sprint_calendar, resolve_window, window_label

__all__ = [
    "SOURCES",
    "SOURCE_LABELS",
    "WINDOW_KINDS",
    "ContextScope",
    "LabelStore",
    "Preview",
    "Selection",
    "SessionLabels",
    "SourceRow",
    "SprintCalendar",
    "Window",
    "coerce_scope",
    "default_tags",
    "drop_run_labels",
    "incognito",
    "latest_planning_state",
    "load_sprint_calendar",
    "normalize_tag",
    "normalize_tags",
    "parse_context_spec",
    "preview_scope",
    "recent_standup_blockers",
    "resolve_scope",
    "resolve_window",
    "wants",
    "window_label",
]
