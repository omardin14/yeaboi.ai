"""The context page's screen: source chips, the window row, the label fields, the preview line.

Drawn in the calling mode's theme so the page reads as part of that mode.
"""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from yeaboi.context.scope import SOURCE_HINTS, SOURCE_LABELS, SOURCES, WINDOW_LABELS
from yeaboi.ui.mode_select._context import CONTEXT_ACTIONS, ContextDraft, ContextPreview
from yeaboi.ui.shared._components import (
    PAD,
    PLANNING_THEME,
    TITLE_ROWS,
    build_action_buttons,
    build_page_panel,
    build_reveal_subtitle,
    calc_viewport,
    planning_title,
)
from yeaboi.ui.shared._scroll import publish_geometry

_HEADER_ROWS = 2 + TITLE_ROWS + 1
_ACTION_ROWS = 4
_FIELD_W = 32

_SUBTITLES = {
    "planning": "What this plan reads from your other sessions",
    "standup": "What this standup reads from your other sessions",
    "retro": "What this retro reads from your other sessions",
    "reporting": "What this report reads from your other sessions",
    "review": "What this review reads from your other sessions",
    "performance": "What this 1:1 or review reads from your other sessions",
    "poker": "What this poker session reads from your other sessions",
}


def _field(label: str, value: str, *, focused: bool, theme) -> Text:
    shown = value if len(value) <= _FIELD_W else "…" + value[-(_FIELD_W - 1) :]
    row = Text(
        f"{PAD}{'▸ ' if focused else '  '}{label:<8}", style=f"bold {theme.accent_bright}" if focused else theme.value
    )
    row.append("[", style=theme.dim)
    row.append(shown, style=theme.value)
    row.append("▏" if focused else " ", style=theme.accent if focused else theme.dim)
    row.append(" " * max(0, _FIELD_W - len(shown)), style=theme.dim)
    row.append("]", style=theme.dim)
    return row


def _build_context_screen(
    draft: ContextDraft,
    preview: ContextPreview,
    *,
    selected: int = 0,
    action_sel: int = 0,
    width: int = 80,
    height: int = 24,
    shimmer_tick: float | None = None,
    sub_reveal: float | None = None,
    theme=None,
    title_fn=None,
    mode: str = "planning",
) -> Panel:
    """One row per source (● on, ○ off, with its count), the window, the label fields, the preview."""
    theme = theme or PLANNING_THEME
    title = (title_fn or planning_title)(shimmer_tick)
    sub = build_reveal_subtitle(_SUBTITLES.get(mode, _SUBTITLES["planning"]), sub_reveal, pad=PAD + "  ")
    rows = draft.rows()

    body: list = [Text("")]
    for name in SOURCES:
        focused = rows[selected] == f"src:{name}"
        on = draft.is_on(name)
        style = f"bold {theme.accent_bright}" if focused else (theme.value if on else theme.muted)
        row = Text(f"{PAD}{'▸ ' if focused else '  '}{'●' if on else '○'} {SOURCE_LABELS[name]}", style=style)
        row.append(f"  ·  {SOURCE_HINTS.get(name, '')}", style=theme.dim)
        count = preview.counts.get(name)
        if count is not None and on:
            row.append(f"  ·  {count}", style=theme.muted)
        body.append(row)

    body.append(Text(""))
    focused = rows[selected] == "window"
    window_label = WINDOW_LABELS[draft.window_kind]
    if draft.window_kind == "sprints":
        window_label = "Last sprint" if draft.count == 1 else f"Last {draft.count} sprints"
    row = Text(
        f"{PAD}{'▸ ' if focused else '  '}Window   ", style=f"bold {theme.accent_bright}" if focused else theme.value
    )
    row.append(f"‹ {window_label} ›", style=theme.accent if focused else theme.value)
    hint = "  ·  ←/→ change · +/- sprints" if draft.window_kind == "sprints" else "  ·  ←/→ change"
    row.append(hint, style=theme.dim)
    body.append(row)
    if draft.window_kind == "custom":
        body.append(_field("From", draft.start, focused=rows[selected] == "from", theme=theme))
        body.append(_field("To", draft.end, focused=rows[selected] == "to", theme=theme))
    body.append(_field("Project", draft.project, focused=rows[selected] == "project", theme=theme))
    body.append(_field("Tags", draft.tags, focused=rows[selected] == "tags", theme=theme))

    body.append(Text(""))
    if draft.sources is not None and not draft.sources:
        body.append(Text(f"{PAD}Incognito — this run reads no other session. It is still saved.", style=theme.dim))
    elif preview.label:
        line = Text(f"{PAD}Reads {preview.label}", style=theme.accent)
        if preview.calendar_source:
            line.append(f"  ·  sprint calendar from {preview.calendar_source}", style=theme.dim)
        body.append(line)
    body.append(
        Text(f"{PAD}Space toggles a source · Tab completes a label · Use keeps it for this mode", style=theme.dim)
    )
    if draft.message:
        body.append(Text(""))
        body.append(Text(f"{PAD}{draft.message}", style=theme.accent))

    viewport_h = calc_viewport(height, header_h=_HEADER_ROWS, action_h=_ACTION_ROWS)
    total = len(body)
    # Keep the focused row on screen when the window is short.
    offset = 0
    focus_line = 1 + (selected if selected < len(SOURCES) else selected + 1)
    if focus_line >= viewport_h:
        offset = focus_line - viewport_h + 1
    visible = body[offset : offset + viewport_h]
    padded = list(visible) + [Text("")] * max(0, viewport_h - len(visible))
    publish_geometry(None, max(0, total - viewport_h), viewport_h)

    btn_top, btn_mid, btn_bot = build_action_buttons(list(CONTEXT_ACTIONS), action_sel)
    content = Group(Text(""), title, Text(""), sub, Group(*padded), Text(""), btn_top, btn_mid, btn_bot)
    return build_page_panel(content, theme=theme, height=height)
