"""What a run may read from other sessions — the scope, as pure data.

A :class:`ContextScope` names the producer modes a run may read (``sources``),
the timeframe (``window``), the project labels and tags the sessions must
carry, and a per-source "newest N" cap (``limits``). ``None`` is today's
unscoped behaviour byte-for-byte; every narrowing is opt-in.

Two twins of the same value: a JSON dict (HTTP bodies, ``ScrumState``) and a
one-line spec string (CLI, MCP). Both round-trip through this module. Nothing
here touches a store — resolution lives in :mod:`yeaboi.context.resolve`.
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: The producer modes a run may read, in the order surfaces list them.
SOURCES: tuple[str, ...] = ("plan", "standup", "retro", "poker", "performance", "analysis", "reporting", "review")

SOURCE_LABELS: dict[str, str] = {
    "plan": "Sprint plans",
    "standup": "Standups",
    "retro": "Retros",
    "poker": "Poker sessions",
    "performance": "1:1s and reviews",
    "analysis": "Analysis profiles",
    "reporting": "Delivery reports",
    "review": "Weekly reviews",
}

#: One line per source, for chips and help text.
SOURCE_HINTS: dict[str, str] = {
    "plan": "sprint framing and roster",
    "standup": "blockers, confidence trend and cadence",
    "retro": "action items, themes and carry-over",
    "poker": "agreed estimates",
    "performance": "open 1:1 actions and review focus",
    "analysis": "team calibration and AC style",
    "reporting": "what shipped last period",
    "review": "last week's actions",
}

WINDOW_KINDS: tuple[str, ...] = ("all", "sprints", "month", "quarter", "year", "custom")

WINDOW_LABELS: dict[str, str] = {
    "all": "Everything",
    "sprints": "Last sprints",
    "month": "Last month",
    "quarter": "Last quarter",
    "year": "Last year",
    "custom": "Custom range",
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPRINTS = re.compile(r"^(\d+)\s*sprints?$")
_SOURCE_TOKEN = re.compile(r"^([a-z]+)(?::(\d+))?$")


def _valid_sources_text() -> str:
    return ", ".join(SOURCES)


@dataclass(frozen=True)
class Window:
    """The timeframe a scope reads over. ``kind`` is one of :data:`WINDOW_KINDS`."""

    kind: str = "all"
    count: int = 0  # sprints only; 0 reads as 1
    start: str = ""  # custom only, ISO date
    end: str = ""  # custom only, ISO date; "" = today

    def __post_init__(self) -> None:
        if self.kind not in WINDOW_KINDS:
            raise ValueError(f"unknown window kind {self.kind!r} — one of {', '.join(WINDOW_KINDS)}")
        if self.count < 0:
            raise ValueError("window count cannot be negative")
        for label, value in (("start", self.start), ("end", self.end)):
            if value and not _ISO_DATE.match(value):
                raise ValueError(f"window {label} must be an ISO date (YYYY-MM-DD), got {value!r}")

    @property
    def bounded(self) -> bool:
        return self.kind != "all"

    def label(self) -> str:
        """A short human label: ``last 2 sprints``, ``last month``, ``2026-06-01 to 2026-08-31``."""
        if self.kind == "all":
            return "everything"
        if self.kind == "sprints":
            n = max(1, self.count)
            return "last sprint" if n == 1 else f"last {n} sprints"
        if self.kind == "custom":
            return f"{self.start or '…'} to {self.end or 'today'}"
        return WINDOW_LABELS[self.kind].lower()

    def to_dict(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.kind == "sprints":
            out["count"] = max(1, self.count)
        if self.kind == "custom":
            out["start"] = self.start
            out["end"] = self.end
        return out

    @classmethod
    def from_dict(cls, data: Mapping | None) -> Window:
        """Tolerant: an unknown kind or a bad date reads as ``all`` with a warning."""
        if not isinstance(data, Mapping):
            return cls()
        kind = str(data.get("kind", "all") or "all").strip().lower()
        if kind not in WINDOW_KINDS:
            logger.warning("Window.from_dict: unknown kind %r — reading everything", kind)
            return cls()
        try:
            count = int(data.get("count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            return cls(
                kind=kind,
                count=max(0, count),
                start=str(data.get("start", "") or ""),
                end=str(data.get("end", "") or ""),
            )
        except ValueError as exc:
            logger.warning("Window.from_dict: %s — reading everything", exc)
            return cls()

    def to_spec(self) -> str:
        if self.kind == "all":
            return "all"
        if self.kind == "sprints":
            n = max(1, self.count)
            return f"{n}sprint" if n == 1 else f"{n}sprints"
        if self.kind == "custom":
            return f"{self.start}..{self.end}" if self.end else f"{self.start}.." if self.start else "all"
        return self.kind


@dataclass(frozen=True)
class ContextScope:
    """The sessions a run may read. Every field narrows; the default narrows nothing."""

    sources: frozenset[str] | None = None  # None = every source; frozenset() = incognito
    window: Window = field(default_factory=Window)
    projects: tuple[str, ...] = ()  # project labels, any of (OR)
    tags: tuple[str, ...] = ()  # tags, all of (AND)
    limits: tuple[tuple[str, int], ...] = ()  # (source, newest N) caps

    def wants(self, source: str) -> bool:
        return self.sources is None or source in self.sources

    @property
    def incognito(self) -> bool:
        return self.sources is not None and not self.sources

    @property
    def narrows(self) -> bool:
        """Whether resolving this scope can change any read at all."""
        return self.sources is not None or self.window.bounded or bool(self.projects or self.tags or self.limits)

    def limit_for(self, source: str) -> int:
        for name, cap in self.limits:
            if name == source:
                return cap
        return 0

    def to_dict(self) -> dict:
        return {
            "sources": None if self.sources is None else sorted(self.sources, key=SOURCES.index),
            "window": self.window.to_dict(),
            "projects": list(self.projects),
            "tags": list(self.tags),
            "limits": {name: cap for name, cap in self.limits},
        }

    @classmethod
    def from_dict(cls, data: Mapping | None) -> ContextScope:
        """The JSON twin, read tolerantly.

        Unknown keys are ignored and unknown sources dropped with a warning. A
        ``sources`` list whose every entry is unknown reads as all-on, never
        incognito: only an explicitly empty list switches everything off.
        """
        if not isinstance(data, Mapping):
            return cls()
        raw_sources = data.get("sources")
        sources: frozenset[str] | None = None
        if isinstance(raw_sources, (list, tuple, set, frozenset)):
            tokens = {str(item).strip().lower() for item in raw_sources if str(item).strip()}
            known = tokens & set(SOURCES)
            if tokens - known:
                logger.warning("ContextScope.from_dict: dropping unknown source(s) %s", sorted(tokens - known))
            if raw_sources and not known and tokens:
                logger.warning("ContextScope.from_dict: no known source in %s — reading everything", sorted(tokens))
                sources = None
            elif not raw_sources:
                sources = frozenset()
            else:
                sources = frozenset(known)
        elif raw_sources is not None:
            logger.warning("ContextScope.from_dict: sources must be a list or null, got %r", type(raw_sources).__name__)
        limits: list[tuple[str, int]] = []
        raw_limits = data.get("limits")
        if isinstance(raw_limits, Mapping):
            for name, cap in raw_limits.items():
                if str(name) not in SOURCES:
                    continue
                try:
                    value = int(cap)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    limits.append((str(name), value))
        return cls(
            sources=sources,
            window=Window.from_dict(data.get("window")),
            projects=_clean_strings(data.get("projects")),
            tags=_clean_strings(data.get("tags")),
            limits=tuple(sorted(limits, key=lambda pair: SOURCES.index(pair[0]))),
        )

    def to_spec(self) -> str:
        """The one-line grammar twin; ``parse_context_spec`` reads it back."""
        if self.incognito:
            return "none"
        if self.sources is None:
            head = "all"
        else:
            head = ",".join(
                f"{name}:{self.limit_for(name)}" if self.limit_for(name) else name
                for name in SOURCES
                if name in self.sources
            )
        if self.window.bounded:
            head = f"{head}@{self.window.to_spec()}"
        parts = [head]
        if self.projects:
            parts.append("project=" + ",".join(_quote(label) for label in self.projects))
        if self.tags:
            parts.append("tags=" + ",".join(_quote(tag) for tag in self.tags))
        return " ".join(parts)


def _clean_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Iterable):
        return ()
    seen: dict[str, None] = {}
    for item in value:
        text = str(item).strip()
        if text:
            seen.setdefault(text, None)
    return tuple(seen)


def _quote(label: str) -> str:
    return f'"{label}"' if any(ch in label for ch in " ,\"'") else label


def wants(scope: ContextScope | None, source: str) -> bool:
    """Whether ``scope`` allows ``source``; an absent scope allows everything."""
    return scope is None or scope.wants(source)


def incognito(scope: ContextScope | None) -> bool:
    """Whether ``scope`` switches every source off; an absent scope never does."""
    return scope is not None and scope.incognito


def coerce_scope(value: ContextScope | Mapping | str | None) -> ContextScope | None:
    """The one entry every engine calls: a scope, its dict, its spec, or nothing.

    A spec string that does not parse raises ``ValueError`` — the surfaces turn
    that into a 400 or a CLI error, never a silent "read nothing".
    """
    if value is None or isinstance(value, ContextScope):
        return value
    if isinstance(value, str):
        return parse_context_spec(value)
    if isinstance(value, Mapping):
        return ContextScope.from_dict(value)
    raise TypeError(f"a context scope is a ContextScope, a dict, a spec string or None — not {type(value).__name__}")


def parse_context_spec(spec: str) -> ContextScope | None:
    """Parse the one-line grammar::

        SPEC    := "" | inherit | none | CLAUSE (WS CLAUSE)*
        CLAUSE  := SOURCES ["@" WINDOW] | window=WINDOW | project=LABELS | tags=TAGS
        SOURCES := all | TOKEN ("," TOKEN)*        TOKEN := SOURCE [":" N]
        WINDOW  := all | N sprint(s) | month | quarter | year | DATE ".." [DATE] | DATE

    ``""``/``inherit`` → ``None`` (the caller's default applies); ``none`` is
    incognito. An unknown source raises ``ValueError`` naming the valid ones —
    a typo must never read as "that source is switched off".
    """
    text = spec.strip()
    if text.lower() in ("", "inherit"):
        return None
    if text.lower() == "none":
        return ContextScope(sources=frozenset())
    try:
        clauses = shlex.split(text)
    except ValueError as exc:
        raise ValueError(f"could not read context spec {spec!r}: {exc}") from None
    explicit: set[str] = set()
    saw_sources = False
    read_all = False
    window: Window | None = None
    projects: list[str] = []
    tags: list[str] = []
    limits: dict[str, int] = {}
    for clause in clauses:
        key, sep, value = clause.partition("=")
        if sep and key.lower() in ("window", "project", "projects", "tag", "tags"):
            word = key.lower()
            if word == "window":
                window = _parse_window(value)
            elif word.startswith("project"):
                projects.extend(_split_labels(value))
            else:
                tags.extend(_split_labels(value))
            continue
        head, at, tail = clause.partition("@")
        if at:
            window = _parse_window(tail)
        parsed, caps = _parse_sources(head)
        saw_sources = True
        if parsed is None:
            read_all = True
        else:
            explicit.update(parsed)
        limits.update(caps)
    sources = None if (read_all or not saw_sources) else explicit
    scope_sources = None if sources is None else frozenset(sources)
    return ContextScope(
        sources=scope_sources,
        window=window or Window(),
        projects=tuple(dict.fromkeys(projects)),
        tags=tuple(dict.fromkeys(tags)),
        limits=tuple(sorted(limits.items(), key=lambda pair: SOURCES.index(pair[0]))),
    )


def _parse_sources(text: str) -> tuple[list[str] | None, dict[str, int]]:
    """``all`` → ``(None, {})``; ``standup,retro:1`` → ``(["standup","retro"], {"retro": 1})``."""
    word = text.strip().lower()
    if not word or word == "all":
        return None, {}
    names: list[str] = []
    caps: dict[str, int] = {}
    for token in word.split(","):
        token = token.strip()
        if not token:
            continue
        match = _SOURCE_TOKEN.match(token)
        if not match or match.group(1) not in SOURCES:
            raise ValueError(f"unknown context source {token.split(':')[0]!r} — valid: {_valid_sources_text()}")
        name, cap = match.group(1), match.group(2)
        names.append(name)
        if cap and int(cap) > 0:
            caps[name] = int(cap)
    return list(dict.fromkeys(names)), caps


def _parse_window(text: str) -> Window:
    word = text.strip().lower()
    if not word or word == "all":
        return Window()
    if word in ("month", "quarter", "year"):
        return Window(kind=word)
    if word == "sprint":
        return Window(kind="sprints", count=1)
    match = _SPRINTS.match(word)
    if match:
        return Window(kind="sprints", count=max(1, int(match.group(1))))
    start, dots, end = word.partition("..")
    if dots or _ISO_DATE.match(word):
        for value in (start, end):
            if value and not _ISO_DATE.match(value):
                raise ValueError(f"window dates must be ISO (YYYY-MM-DD), got {value!r}")
        return Window(kind="custom", start=start, end=end)
    raise ValueError(
        f"unknown window {text!r} — use all, <N>sprints, month, quarter, year, or YYYY-MM-DD[..YYYY-MM-DD]"
    )


def _split_labels(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
