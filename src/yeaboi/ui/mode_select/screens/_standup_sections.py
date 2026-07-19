"""Section registry + builders for the sectioned Daily Standup page.

Mirrors the team-analysis pattern (``_analysis_sections.py``): the standup page
shows an overview (headline stats + a selectable list of section cards) and a
detail view per card. Unlike analysis, the card list is COMPUTED per report —
each team member gets their own card — so the registry is a set of functions
over the standup data dict, not a static table.

Card keys: ``"summary"``, ``"sprint"``, ``"my_update"`` (the standup user's own
card), ``"team"`` (one row for everyone else — expands inline into
``"member:<name>"`` sub-rows when ``data["team_expanded"]`` is set),
``"activity"``, ``"schedule"``, and ``"notices"`` (only when the report carries
warnings).

All colours come from ``STANDUP_THEME`` (no hardcoded values) and all rows are
height-1 ``Text`` lines, so the viewport is a plain list slice — no need for
the analysis module's height-aware packer.

# See README: "Daily Standup" — TUI page
"""

from __future__ import annotations

import textwrap

from rich.text import Text

from yeaboi.ui.shared._components import PAD, Theme

_TEASER_W = 46  # max teaser length on an overview section row


class _StandupCtx:
    """Tiny line accumulator for standup screens (all rows are height 1).

    Tracks ``first_card_row`` so the overview can auto-scroll the selected
    section row into view (same idea as _TaCtx.overview_first_card_row).
    """

    def __init__(self, theme: Theme, width: int) -> None:
        self.lines: list[Text] = []
        self.theme = theme
        self.width = width
        self.first_card_row: int | None = None

    def add(self, line: Text) -> None:
        self.lines.append(line)

    def blank(self) -> None:
        self.lines.append(Text(""))

    def heading(self, text: str) -> None:
        self.blank()
        h = Text(PAD + "  ", justify="left")
        h.append(text, style=f"bold {self.theme.accent}")
        self.lines.append(h)
        self.lines.append(Text(PAD + "  " + "─" * min(len(text), 40), style=self.theme.sep, justify="left"))

    def row(self, label: str, value: str, value_style: str = "") -> None:
        r = Text(PAD + "    ", justify="left")
        r.append(f"{label}:  ", style=self.theme.muted)
        r.append(str(value), style=value_style or self.theme.value)
        self.lines.append(r)

    def line(self, text: str, style: str = "") -> None:
        self.lines.append(Text(PAD + "    " + text, style=style or self.theme.value, justify="left"))

    def wrapped(self, text: str, style: str, *, indent: str = "    ", preserve_newlines: bool = False) -> None:
        """Append word-wrapped lines; optionally honour explicit newlines.

        preserve_newlines keeps the user's own paragraph breaks (multi-line
        self-reports typed with Alt+Enter) instead of collapsing them.
        """
        wrap_w = max(24, self.width - len(PAD) - len(indent) - 6)
        paragraphs = text.splitlines() if preserve_newlines else [text]
        for para in paragraphs or [""]:
            for chunk in textwrap.wrap(para, width=wrap_w) or [""]:
                self.lines.append(Text(PAD + indent + chunk, style=style, justify="left"))


# ---------------------------------------------------------------------------
# Card registry (computed per report)
# ---------------------------------------------------------------------------


def standup_card_order(data: dict) -> list[str]:
    """Return the ordered card keys for the current standup data.

    With no generated report yet only Schedule is available. With a report the
    standup user's own card is a top-level "my_update" row and everyone else
    lives under a single "team" row — expanded inline into ``member:<name>``
    sub-rows when ``data["team_expanded"]`` is set. Notices appears only when
    needed.
    """
    report = data.get("report")
    if report is None:
        return ["schedule"]
    order = ["summary", "sprint", "my_update", "team"]
    if data.get("team_expanded"):
        order += [f"member:{m.name}" for m in _team_members(data)]
    order += ["activity", "schedule"]
    if report.warnings:
        order.append("notices")
    return order


def _team_members(data: dict) -> list:
    """Member updates excluding the standup user (their card is "my_update")."""
    report = data.get("report")
    if report is None:
        return []
    my_name = data.get("my_name", "")
    return [m for m in report.member_updates if m.name != my_name]


def _confidence_style(theme: Theme, label: str) -> str:
    return {"On track": theme.good, "At risk": theme.warn, "Behind": theme.bad}.get(label, theme.muted)


def _member(data: dict, name: str):
    report = data.get("report")
    if report is None:
        return None
    return next((m for m in report.member_updates if m.name == name), None)


def _confidence_text(report) -> str:
    conf = report.confidence_label or "unknown"
    if report.confidence_label and report.confidence_label != "Insufficient data":
        conf = f"{report.confidence_label}  ·  {report.confidence_pct}%"
    return conf


def standup_card_title(key: str, data: dict) -> str:
    """Human title for a card key; member sub-rows are just the member's name."""
    if key.startswith("member:"):
        return key[len("member:") :]
    return {
        "summary": "Team Summary",
        "sprint": "Sprint & Confidence",
        "my_update": "My Update",
        "team": "Team",
        "activity": "Activity",
        "schedule": "Schedule",
        "notices": "⚠ Notices",
    }.get(key, key)


def standup_card_teaser(key: str, data: dict) -> str:
    """One-line dim teaser shown next to each section row on the overview."""
    report = data.get("report")
    config = data.get("config") or {}
    if key == "summary":
        text = (report.team_summary if report else "") or "No summary yet"
        return text[: _TEASER_W - 1] + "…" if len(text) > _TEASER_W else text
    if key == "sprint":
        if report is None:
            return ""
        day = f"Day {report.sprint_day}/{report.sprint_total_days}" if report.sprint_total_days else ""
        return "  ·  ".join(x for x in (day, _confidence_text(report)) if x)
    if key == "my_update":
        m = _member(data, data.get("my_name", ""))
        if m is None:
            return "No update yet — Generate asks for it"
        gist = (m.summary or "No activity detected.")[:_TEASER_W]
        return f"{gist} · ✍ update" if m.self_report else gist
    if key == "team":
        n = len(_team_members(data))
        if n == 0:
            return "No member updates"
        hint = "Enter to collapse" if data.get("team_expanded") else "Enter to expand"
        return f"{n} member update{'s' if n != 1 else ''} · {hint}"
    if key.startswith("member:"):
        m = _member(data, key[len("member:") :])
        if m is None:
            return ""
        gist = (m.summary or "No activity detected.")[:_TEASER_W]
        return f"{gist} · ✍ update" if m.self_report else gist
    if key == "activity":
        if report is None or not report.activity_counts:
            return "no sources"
        return ", ".join(f"{src}: {n}" for src, n in report.activity_counts)[:_TEASER_W]
    if key == "schedule":
        if not config:
            return "Not configured"
        state = "Enabled" if config.get("enabled") else "Off"
        return f"{state} · {config.get('time', '—')} · {config.get('weekdays', '—')}"
    if key == "notices":
        n = len(report.warnings) if report else 0
        return f"{n} notice{'s' if n != 1 else ''}"
    return ""


# ---------------------------------------------------------------------------
# Detail builders
# ---------------------------------------------------------------------------


def _link_row(ctx: _StandupCtx, label: str, url: str) -> None:
    """One height-1 link row: clickable label (OSC-8 hyperlink) + truncated dim URL.

    The URL is truncated to keep the row a single terminal line — the detail
    viewport slices height-1 Text rows, so a wrapped line would break the
    scroll math. Both segments carry the ``link`` style, so terminals that
    support hyperlinks make them clickable; others still show the address.
    """
    theme = ctx.theme
    row = Text(PAD + "      ", justify="left")
    row.append("↗ ", style=theme.dim)
    row.append(label or url, style=f"underline {theme.accent_bright} link {url}")
    room = ctx.width - len(PAD) - 10 - len(label or url)
    if room > 16:
        shown = url if len(url) <= room else url[: room - 1] + "…"
        row.append(f"  {shown}", style=f"{theme.dim} link {url}")
    ctx.add(row)


def _detail_summary(ctx: _StandupCtx, data: dict) -> None:
    report = data["report"]
    theme = ctx.theme
    ctx.heading(f"Team Summary — {report.date}")
    ctx.wrapped(report.team_summary or "No team summary was produced.", theme.value)
    if report.confidence_rationale:
        ctx.blank()
        ctx.row("Confidence", _confidence_text(report), _confidence_style(theme, report.confidence_label))
        ctx.wrapped(report.confidence_rationale, theme.dim, indent="      ")


def _detail_sprint(ctx: _StandupCtx, data: dict) -> None:
    report = data["report"]
    theme = ctx.theme
    ctx.heading("Sprint & Confidence")
    ctx.row("Sprint", report.sprint_name or "unknown")
    if report.sprint_total_days:
        ctx.row("Day", f"{report.sprint_day} of {report.sprint_total_days}")
    ctx.row("Confidence", _confidence_text(report), _confidence_style(theme, report.confidence_label))
    if report.confidence_rationale:
        ctx.wrapped(report.confidence_rationale, theme.dim, indent="      ")


def _detail_member(ctx: _StandupCtx, data: dict, name: str) -> None:
    theme = ctx.theme
    m = _member(data, name)
    ctx.heading(standup_card_title(f"member:{name}", data))
    if m is None:
        ctx.line("No update found for this member.", theme.muted)
        return
    if m.self_report:
        ctx.line("✍ In their words", theme.accent_bright)
        # preserve_newlines: multi-line updates typed with Alt+Enter keep their breaks.
        ctx.wrapped(m.self_report, theme.value, indent="      ", preserve_newlines=True)
        ctx.blank()
    ctx.line("Activity analysis", theme.accent_bright)
    ctx.wrapped(m.summary or "No activity detected.", theme.desc, indent="      ")
    if m.blockers:
        ctx.blank()
        ctx.wrapped(f"⚠ Blocker: {m.blockers}", theme.warn, indent="      ")
    if getattr(m, "links", ()):
        ctx.blank()
        ctx.line("Links", theme.accent_bright)
        for label, url in m.links:
            _link_row(ctx, label, url)
    ctx.blank()
    source_label = {
        "combined": "self-report + tracked activity",
        "self-reported": "self-reported (no tracked activity)",
        "inferred": "inferred from tracked activity",
    }.get(m.source, m.source)
    ctx.row("Based on", source_label, theme.dim)


def _detail_activity(ctx: _StandupCtx, data: dict) -> None:
    report = data["report"]
    theme = ctx.theme
    ctx.heading("Activity")
    if report.activity_window:
        ctx.row("Window", report.activity_window, theme.dim)
    if report.activity_counts:
        for src, n in report.activity_counts:
            ctx.row(src.replace("_", " ").title(), f"{n} item{'s' if n != 1 else ''}")
        ctx.blank()
        ctx.wrapped(
            "Counts are the items examined per source since the last standup window. "
            "Sources are enabled by their identifying setting (GitHub repo, Jira project, "
            "local repo path, Confluence space, Notion root).",
            theme.dim,
        )
    else:
        ctx.wrapped(
            "No activity sources reported anything. Configure a local repo path here, or connect "
            "GitHub/Jira/Azure DevOps/Confluence/Notion in .env to infer updates from real activity.",
            theme.muted,
        )
    if getattr(report, "skipped_sources", ()):
        ctx.blank()
        ctx.heading("Not scanned")
        for src, reason in report.skipped_sources:
            ctx.row(src.replace("_", " ").title(), reason, theme.muted)


def _detail_schedule(ctx: _StandupCtx, data: dict) -> None:
    theme = ctx.theme
    config = data.get("config") or {}
    schedule = data.get("schedule") or {}
    ctx.heading("Schedule")
    if config:
        ctx.row(
            "Enabled", "yes" if config.get("enabled") else "no", theme.good if config.get("enabled") else theme.muted
        )
        standup_time = config.get("time", "—")
        lead = config.get("lead_minutes", 10)
        ctx.row("Standup time", standup_time)
        if standup_time and standup_time != "—":
            from yeaboi.standup.scheduler import run_time_str

            ctx.row("Runs at", f"{run_time_str(standup_time, lead)}  ({lead} min before)")
        ctx.row("Weekdays", config.get("weekdays", "—"))
        ctx.row("Channels", ", ".join(config.get("delivery_channels", [])) or "—")
        if config.get("repo_path"):
            ctx.row("Local repo", config["repo_path"])
        if config.get("my_aliases"):
            ctx.row("My aliases", config["my_aliases"])
    else:
        ctx.line("Not configured — press Configure to set a time and delivery.", theme.muted)
    installed = schedule.get("installed")
    if installed is not None:
        ctx.row(
            "OS schedule",
            f"installed ({schedule.get('platform', '?')})" if installed else "not installed",
            theme.good if installed else theme.muted,
        )


def _detail_notices(ctx: _StandupCtx, data: dict) -> None:
    report = data["report"]
    ctx.heading("⚠ Notices")
    for w in report.warnings:
        ctx.wrapped(f"- {w}", ctx.theme.warn)


def build_standup_detail(ctx: _StandupCtx, key: str, data: dict) -> None:
    """Append the detail-view lines for one card into ctx."""
    if key == "my_update":
        _detail_member(ctx, data, data.get("my_name", ""))
        return
    if key.startswith("member:"):
        _detail_member(ctx, data, key[len("member:") :])
        return
    builder = {
        "summary": _detail_summary,
        "sprint": _detail_sprint,
        "activity": _detail_activity,
        "schedule": _detail_schedule,
        "notices": _detail_notices,
    }.get(key)
    if builder is None:
        ctx.line("Unknown section.", ctx.theme.muted)
        return
    builder(ctx, data)


# ---------------------------------------------------------------------------
# Overview builder
# ---------------------------------------------------------------------------


def build_standup_overview(ctx: _StandupCtx, data: dict, selected_card: int) -> None:
    """Append the overview lines: headline stats + the selectable section list."""
    theme = ctx.theme
    report = data.get("report")
    config = data.get("config") or {}

    message = data.get("message", "")
    if message:
        ctx.add(Text(PAD + "  " + message, style=theme.accent_bright, justify="left"))

    if report is not None:
        ctx.heading(f"Latest Standup — {report.date}")
        ctx.row("Sprint", report.sprint_name or "unknown")
        if report.sprint_total_days:
            ctx.row("Day", f"{report.sprint_day} of {report.sprint_total_days}")
        ctx.row("Confidence", _confidence_text(report), _confidence_style(theme, report.confidence_label))
    else:
        ctx.heading("Latest Standup")
        ctx.line("No standup generated yet. Press Generate to create one.", theme.muted)
        if not config:
            ctx.line("Schedule not configured — press Configure to set a time.", theme.muted)

    ctx.heading("Sections")
    ctx.add(Text(PAD + "    ↑/↓ section  ·  Enter to open  ·  ←/→ buttons", style=theme.dim, justify="left"))
    ctx.first_card_row = len(ctx.lines)
    order = standup_card_order(data)
    for i, key in enumerate(order):
        selected = i == selected_card
        row = Text(PAD + "  ", justify="left")
        row.append("▸ " if selected else "  ", style=theme.accent if selected else theme.dim)
        title = standup_card_title(key, data)
        if key == "team":  # trailing chevron shows the inline expand state
            title += "  ▾" if data.get("team_expanded") else "  ▸"
        elif key.startswith("member:"):
            # Member sub-rows nest under Team with tree guides (└ on the last).
            nxt = order[i + 1] if i + 1 < len(order) else ""
            title = f"  {'├' if nxt.startswith('member:') else '└'} {title}"
        row.append(f"{title:<22s}", style=f"bold {theme.accent}" if selected else theme.value)
        teaser = standup_card_teaser(key, data)
        if teaser:
            row.append(f"  {teaser}", style=theme.muted if selected else theme.dim)
        ctx.add(row)
