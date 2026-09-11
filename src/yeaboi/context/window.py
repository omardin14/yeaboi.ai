"""Turning a :class:`~yeaboi.context.scope.Window` into two dates.

Month, quarter and year are rolling windows ending today (30, 91 and 365
days). A sprint window needs a :class:`SprintCalendar`, which
:func:`load_sprint_calendar` derives from the best source available: a live
tracker, else the newest plan, else the sprint settings, else two-week
sprints anchored on Monday of this week. Everything but the loader is pure.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from yeaboi.context.scope import Window
from yeaboi.reporting.sprints import SprintRef
from yeaboi.timeparse import parse_date

logger = logging.getLogger(__name__)

_ROLLING_DAYS = {"month": 30, "quarter": 91, "year": 365}
_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")
_MEMO_SECONDS = 60.0
_memo: dict[tuple[str, str, bool], tuple[float, SprintCalendar]] = {}


@dataclass(frozen=True)
class SprintCalendar:
    """A sprint grid: a known start, a length, and where the grid came from."""

    anchor: date
    length_weeks: int
    source: str  # "tracker" | "plan" | "settings" | "default"
    numbered_from: int = 1  # the sprint number at ``anchor``, when a plan knows it
    known: tuple[SprintRef, ...] = ()  # dated sprints from the tracker or the plan, oldest first

    @property
    def length(self) -> timedelta:
        return timedelta(weeks=max(1, self.length_weeks))

    def _index(self, on: date) -> int:
        """How many whole sprints ``on`` lies after ``anchor`` (negative before it)."""
        return (on - self.anchor).days // self.length.days

    def sprint_bounds(self, on: date) -> tuple[date, date]:
        """The sprint containing ``on``: a known dated sprint when one covers it, else the grid."""
        for ref in self.known:
            if ref.start_date and ref.end_date and ref.start_date <= on.isoformat() <= ref.end_date:
                return parse_date(ref.start_date), parse_date(ref.end_date)
        start = self.anchor + self.length * self._index(on)
        return start, start + self.length - timedelta(days=1)

    def sprint_number(self, on: date) -> int | None:
        """The sprint number at ``on`` when it can be known; ``None`` otherwise."""
        for ref in self.known:
            if ref.start_date and ref.end_date and ref.start_date <= on.isoformat() <= ref.end_date:
                match = _TRAILING_NUMBER.search(ref.name)
                if match:
                    return int(match.group(1))
                break
        if self.source == "tracker":
            return None
        number = self.numbered_from + self._index(on)
        return number if number >= 1 else None


def resolve_window(window: Window, *, today: date, calendar: SprintCalendar | None = None) -> tuple[str, str]:
    """``(start_iso, end_iso)`` inclusive; ``("", "")`` when the window is unbounded.

    A sprint window without a calendar falls back to two-week sprints anchored
    on ``today``. A custom window with swapped bounds is normalised; a bad
    date raises ``ValueError`` (the surfaces turn it into a 400).
    """
    if window.kind == "all":
        return "", ""
    if window.kind == "custom":
        if not window.start and not window.end:
            return "", ""
        start = parse_date(window.start) if window.start else None
        end = parse_date(window.end) if window.end else today
        if start is None:
            return "", end.isoformat()
        if start > end:
            start, end = end, start
        return start.isoformat(), end.isoformat()
    if window.kind == "sprints":
        cal = calendar or SprintCalendar(anchor=today, length_weeks=2, source="default")
        count = max(1, window.count)
        current_start, _ = cal.sprint_bounds(today)
        start = current_start - cal.length * (count - 1)
        return start.isoformat(), today.isoformat()
    return (today - timedelta(days=_ROLLING_DAYS[window.kind])).isoformat(), today.isoformat()


def window_label(start: str, end: str) -> str:
    """``4 Aug – 11 Sep`` for a bounded window, ``all time`` otherwise."""
    if not start and not end:
        return "all time"
    if not start:
        return f"until {_day(end)}"
    if not end:
        return f"from {_day(start)}"
    first, last = parse_date(start), parse_date(end)
    if first.year != last.year:
        return f"{_day(start, year=True)} – {_day(end, year=True)}"
    return f"{_day(start)} – {_day(end)}"


def _day(iso: str, *, year: bool = False) -> str:
    value = parse_date(iso)
    text = f"{value.day} {value.strftime('%b')}"
    return f"{text} {value.year}" if year else text


def load_sprint_calendar(*, today: date, db_path: Path | None = None, use_tracker: bool = True) -> SprintCalendar:
    """The sprint grid in use, from the best source available. Never raises.

    Order: a configured tracker's sprint list, the newest plan's
    ``sprint_start_date`` + ``sprint_length_weeks``, the ``YEABOI_SPRINT_*``
    settings, then two-week sprints from Monday of this week. Memoised for a
    minute so a preview never costs a tracker call per keystroke.
    """
    key = (str(db_path or ""), today.isoformat(), use_tracker)
    cached = _memo.get(key)
    if cached and time.monotonic() - cached[0] < _MEMO_SECONDS:
        return cached[1]
    calendar = (
        (_from_tracker() if use_tracker else None)
        or _from_plan(db_path)
        or _from_settings()
        or SprintCalendar(
            anchor=today - timedelta(days=today.weekday()), length_weeks=_settings_length(), source="default"
        )
    )
    logger.info(
        "sprint calendar: source=%s anchor=%s length=%dw", calendar.source, calendar.anchor, calendar.length_weeks
    )
    _memo[key] = (time.monotonic(), calendar)
    return calendar


def clear_calendar_memo() -> None:
    """Forget cached calendars (tests, and a settings write)."""
    _memo.clear()


def _from_tracker() -> SprintCalendar | None:
    try:
        from yeaboi.config import get_azure_devops_project, get_jira_project_key

        jira = get_jira_project_key() or ""
        azdo = get_azure_devops_project() or ""
        if not jira and not azdo:
            return None
        from yeaboi.reporting.sprints import list_sprints

        refs = tuple(r for r in list_sprints(None, jira_project=jira, azdo_project=azdo) if r.start_date and r.end_date)
    except Exception:  # noqa: BLE001 — a tracker outage must not stop a run
        logger.debug("sprint calendar: tracker read failed", exc_info=True)
        return None
    if not refs:
        return None
    newest = refs[-1]
    span_days = (parse_date(newest.end_date) - parse_date(newest.start_date)).days + 1
    return SprintCalendar(
        anchor=parse_date(newest.start_date),
        length_weeks=max(1, round(span_days / 7)),
        source="tracker",
        known=refs,
    )


def _from_plan(db_path: Path | None) -> SprintCalendar | None:
    try:
        from yeaboi.ship.plans import latest_plan_with_work

        found = latest_plan_with_work(db_path)
    except Exception:  # noqa: BLE001
        logger.debug("sprint calendar: plan read failed", exc_info=True)
        return None
    if not found:
        return None
    state = found[0]
    start_str = str(state.get("sprint_start_date") or "")[:10]
    if not start_str:
        return None
    try:
        anchor = parse_date(start_str)
    except (TypeError, ValueError):
        return None
    try:
        weeks = max(1, int(state.get("sprint_length_weeks") or 2))
    except (TypeError, ValueError):
        weeks = 2
    try:
        numbered_from = int(state.get("starting_sprint_number") or 0)
    except (TypeError, ValueError):
        numbered_from = 0
    known = []
    for idx, sprint in enumerate(state.get("sprints") or ()):
        name = getattr(sprint, "name", None) if not isinstance(sprint, dict) else sprint.get("name")
        start = anchor + timedelta(weeks=weeks * idx)
        end = start + timedelta(weeks=weeks) - timedelta(days=1)
        known.append(
            SprintRef(
                name=str(name or f"Sprint {idx + 1}"),
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                source="plan",
            )
        )
    return SprintCalendar(
        anchor=anchor,
        length_weeks=weeks,
        source="plan",
        numbered_from=numbered_from if numbered_from >= 1 else 1,
        known=tuple(known),
    )


def _settings_length() -> int:
    from yeaboi.config import get_sprint_length_weeks

    return get_sprint_length_weeks()


def _from_settings() -> SprintCalendar | None:
    from yeaboi.config import get_sprint_anchor_date

    anchor = get_sprint_anchor_date()
    if not anchor:
        return None
    return SprintCalendar(anchor=parse_date(anchor), length_weeks=_settings_length(), source="settings")
