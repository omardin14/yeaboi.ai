"""Rendering for a StandupReport — one source of truth for every surface.

Plaintext is used by Slack/email/desktop delivery; the Rich form is used by the
terminal delivery channel and the TUI standup page. Keeping both here means the
report looks consistent everywhere and no surface re-implements the layout.

# See README: "Daily Standup" — delivery, TUI page
"""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from scrum_agent.agent.state import StandupReport

# Emoji markers per confidence label — used in plaintext (Slack/email) output.
_CONFIDENCE_EMOJI = {
    "On track": "🟢",
    "At risk": "🟡",
    "Behind": "🔴",
    "Insufficient data": "⚪",
}


def _sprint_line(report: StandupReport) -> str:
    if report.sprint_total_days:
        return f"{report.sprint_name or 'Sprint'} — day {report.sprint_day} of {report.sprint_total_days}"
    return report.sprint_name or "Sprint (dates unknown)"


def _confidence_line(report: StandupReport) -> str:
    emoji = _CONFIDENCE_EMOJI.get(report.confidence_label, "")
    label = report.confidence_label or "Unknown"
    pct = f" ({report.confidence_pct}%)" if report.confidence_label not in ("", "Insufficient data") else ""
    return f"{emoji} {label}{pct}".strip()


def format_standup_lines(report: StandupReport) -> list[str]:
    """Return the standup as a list of plain-text lines (no ANSI)."""
    lines: list[str] = [
        f"Daily Standup — {report.date}",
        _sprint_line(report),
        f"Confidence: {_confidence_line(report)}",
    ]
    if report.confidence_rationale:
        lines.append(f"  {report.confidence_rationale}")
    # Surface problems up top so they're never missed (missing key, source 401/403).
    if report.warnings:
        lines.append("")
        lines.append("⚠ Notices:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    lines.append("")

    if report.team_summary:
        lines.append("Team summary:")
        lines.append(f"  {report.team_summary}")
        lines.append("")

    if report.member_updates:
        lines.append("Updates:")
        for m in report.member_updates:
            tag = "✍️" if m.source == "self-reported" else "•"
            lines.append(f"  {tag} {m.name}: {m.summary}")
            if m.blockers:
                lines.append(f"      ⚠ Blocker: {m.blockers}")
    else:
        lines.append("No individual updates.")

    if report.activity_counts:
        counts = ", ".join(f"{src}: {n}" for src, n in report.activity_counts)
        lines.append("")
        lines.append(f"Activity examined — {counts}")
    return lines


def format_standup_plaintext(report: StandupReport) -> str:
    """Return the standup as a single plain-text string (for Slack/email/desktop)."""
    return "\n".join(format_standup_lines(report))


def format_standup_rich(report: StandupReport, *, accent: str = "rgb(200,100,180)") -> Group:
    """Return a Rich renderable for terminal / TUI display."""
    body: list[Text] = []
    header = Text(justify="left")
    header.append(f"Daily Standup — {report.date}", style=f"bold {accent}")
    body.append(header)
    body.append(Text(_sprint_line(report), style="dim"))

    conf = Text()
    conf.append("Confidence: ", style="dim")
    conf.append(_confidence_line(report), style="bold")
    body.append(conf)
    if report.confidence_rationale:
        body.append(Text(f"  {report.confidence_rationale}", style="dim"))
    body.append(Text(""))

    # Notices up top — auth/API-key problems must be seen, never silently empty.
    if report.warnings:
        body.append(Text("⚠ Notices", style="bold rgb(220,180,60)"))
        for w in report.warnings:
            body.append(Text(f"  - {w}", style="rgb(220,180,60)"))
        body.append(Text(""))

    if report.team_summary:
        body.append(Text("Team summary", style=f"bold {accent}"))
        body.append(Text(f"  {report.team_summary}"))
        body.append(Text(""))

    if report.member_updates:
        body.append(Text("Updates", style=f"bold {accent}"))
        for m in report.member_updates:
            row = Text()
            tag = "✍" if m.source == "self-reported" else "•"
            row.append(f"  {tag} ", style="dim")
            row.append(f"{m.name}: ", style="bold")
            row.append(m.summary or "(no activity)")
            body.append(row)
            if m.blockers:
                body.append(Text(f"      ⚠ Blocker: {m.blockers}", style="rgb(220,180,60)"))
    else:
        body.append(Text("No individual updates.", style="dim"))

    return Group(*body)
