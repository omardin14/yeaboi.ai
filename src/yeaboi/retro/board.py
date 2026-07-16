"""The live, in-memory retro board — the single source of truth during a session.

A retro is collaborative: while the host's TUI is open, teammates POST cards from
their browsers (retro/server.py) on background HTTP threads, and the TUI render
loop reads the board every frame on the main thread. Two-thread access means the
card list MUST be guarded — ``RetroBoard`` owns one ``threading.Lock`` and is the
only object that ever touches ``_cards``.

Concurrency contract (see plan "Concurrency / shutdown checklist"):
  * ``_cards`` is only ever mutated while holding ``_lock``.
  * Readers take a *copy* of the list inside the lock, then work on the copy
    outside — the lock is never held across a Rich render or a JSON dump.
  * ``_revision`` is bumped on every mutation, giving both the browser poller and
    the TUI an O(1) "did anything change?" check.

The frozen, serializable artifacts (``RetroCard``, ``RetroReport``) live in
agent/state.py alongside StandupReport; this module owns only the mutable live
object and the board → report snapshot.

# See README: "Session Management" — Retro mode artifacts
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import UTC, date, datetime
from uuid import uuid4

from yeaboi.agent.state import RetroCard, RetroReport

# The four canonical grids. Keys are stable identifiers used by the store, the
# browser page, and the exporter; labels are the human-facing headings.
RETRO_GRIDS: tuple[str, ...] = ("went_well", "didnt_go_well", "action_items", "demos")
RETRO_GRID_LABELS: dict[str, str] = {
    "went_well": "What went well",
    "didnt_go_well": "What didn't go well",
    "action_items": "Action items",
    "demos": "Demos",
}

# Canonical, server-validated sets shared with the browser page (retro/page.py
# injects these so client and server agree). Reactions/avatars from a LAN peer are
# rejected unless they're in these tuples — bounding what can be stored/rendered.
REACTION_EMOJIS: tuple[str, ...] = ("👍", "❤️", "🎉", "😂", "🔥", "😢", "🚀", "👀")
AVATARS: tuple[str, ...] = (
    "🤠",
    "👻",
    "🐙",
    "🦄",
    "🐸",
    "🦊",
    "🐼",
    "🐧",
    "🦖",
    "🐝",
    "🌮",
    "🍕",
    "👽",
    "🤖",
    "🎃",
    "🦩",
    "🐳",
    "🦉",
    "🌵",
    "🍄",
    "⚡",
    "🌈",
    "🪐",
    "🦆",
)

# Input caps — bound memory and blunt abuse from a LAN peer (see plan "Security").
_MAX_TEXT = 500
_MAX_AUTHOR = 60
_MAX_CARDS = 500
_PRESENCE_TTL = 12.0  # seconds a participant stays "here"/"typing" after their last heartbeat
_MAX_TIMER = 3600  # cap a shared countdown at one hour


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RetroBoard:
    """Thread-safe live card store for one retro session.

    The HTTP server thread(s) call :meth:`add_card`; the TUI render thread calls
    :meth:`snapshot`/:meth:`cards_by_grid` once per frame. All state access is
    serialized through ``_lock``.
    """

    def __init__(self, session_id: str, project_name: str = "", sprint_name: str = "") -> None:
        self.session_id = session_id
        self.project_name = project_name
        self.sprint_name = sprint_name
        self.created_at = _now_iso()
        self._cards: list[RetroCard] = []
        self._revision = 0
        self._lock = threading.Lock()
        # All guarded by _lock, same as _cards.
        self._reactions: dict[str, dict[str, set[str]]] = {}  # card_id -> emoji -> {pid, …}
        # Recent reaction *events* — a small ring buffer the browser poll drains to
        # animate each new reaction exactly once (floating emoji seen by everyone,
        # the same broadcast-by-polling trick the shared timer uses). Add-only:
        # un-reacting never animates. Each event is {"id": int, "emoji": str}.
        self._reaction_events: deque[dict] = deque(maxlen=25)
        self._reaction_seq = 0
        self._card_owner: dict[str, str] = {}  # card_id -> creator pid (edit/delete permission)
        self._presence: dict[str, dict] = {}  # pid -> {name, avatar, typing_grid, last_seen}
        self._timer: dict = {"running": False, "end_epoch": None, "duration": 0}

    def add_card(self, *, grid: str, text: str, author: str, origin: str = "web", pid: str = "") -> RetroCard | None:
        """Add one card, validating + capping inputs. Returns the card, or None if invalid.

        Card text/author are stripped and length-capped here so an oversized or
        empty payload from the browser can never bloat the board. ``pid`` (the
        creator's browser id) is recorded so only they can later edit/delete it.
        """
        grid = grid if grid in RETRO_GRIDS else ""
        text = (text or "").strip()[:_MAX_TEXT]
        author = (author or "").strip()[:_MAX_AUTHOR] or "anon"
        if not grid or not text:
            return None
        card = RetroCard(
            id=uuid4().hex[:12],
            grid=grid,
            text=text,
            author=author,
            created_at=_now_iso(),
            origin=origin,
        )
        with self._lock:
            if len(self._cards) >= _MAX_CARDS:
                return None
            self._cards.append(card)
            if pid:
                self._card_owner[card.id] = pid
            self._revision += 1
        return card

    def add_ai_cards(self, texts: list[str]) -> int:
        """Append LLM-generated action items (origin="ai"). Returns the count added."""
        added = 0
        with self._lock:
            for t in texts:
                t = (t or "").strip()[:_MAX_TEXT]
                if not t or len(self._cards) >= _MAX_CARDS:
                    continue
                self._cards.append(
                    RetroCard(
                        id=uuid4().hex[:12],
                        grid="action_items",
                        text=t,
                        author="AI",
                        created_at=_now_iso(),
                        origin="ai",
                    )
                )
                self._revision += 1
                added += 1
        return added

    def snapshot(self) -> tuple[int, list[RetroCard]]:
        """Return an atomic (revision, cards-copy). Callers never see a torn list."""
        with self._lock:
            return self._revision, list(self._cards)

    def cards_by_grid(self) -> dict[str, list[RetroCard]]:
        """Return cards grouped by grid key, preserving insertion order."""
        _, cards = self.snapshot()
        out: dict[str, list[RetroCard]] = {g: [] for g in RETRO_GRIDS}
        for c in cards:
            out.setdefault(c.grid, []).append(c)
        return out

    def revision(self) -> int:
        """Return the current mutation counter (cheap change-detection)."""
        with self._lock:
            return self._revision

    def total(self) -> int:
        """Return the number of cards currently on the board."""
        with self._lock:
            return len(self._cards)

    # ── Edit / delete / move ──────────────────────────────────────────────
    #
    # Edit and delete are AUTHOR-ONLY (checked against _card_owner); moving a card
    # is open to everyone (arranging the board is collaborative). Cards are frozen,
    # so an edit/move produces a replacement via dataclasses.replace.

    def _index_of_locked(self, card_id: str) -> int:
        for i, c in enumerate(self._cards):
            if c.id == card_id:
                return i
        return -1

    def edit_card(self, card_id: str, text: str, pid: str) -> bool:
        """Replace a card's text. Author-only. Returns True on success."""
        from dataclasses import replace

        text = (text or "").strip()[:_MAX_TEXT]
        if not text:
            return False
        with self._lock:
            if self._card_owner.get(card_id) != pid or not pid:
                return False
            i = self._index_of_locked(card_id)
            if i < 0:
                return False
            self._cards[i] = replace(self._cards[i], text=text)
            self._revision += 1
            return True

    def delete_card(self, card_id: str, pid: str) -> bool:
        """Delete a card (and its reactions/owner). Author-only. Returns True on success."""
        with self._lock:
            if self._card_owner.get(card_id) != pid or not pid:
                return False
            i = self._index_of_locked(card_id)
            if i < 0:
                return False
            del self._cards[i]
            self._reactions.pop(card_id, None)
            self._card_owner.pop(card_id, None)
            self._revision += 1
            return True

    def move_card(self, card_id: str, to_grid: str, to_index: int, pid: str = "") -> bool:
        """Move a card to ``to_grid`` at grid-local position ``to_index``. Open to anyone.

        Rebuilds the flat card list so the moved card sits at the requested
        position among the target grid's cards (grid-local index → flat position),
        replacing the card's grid if it changed.
        """
        from dataclasses import replace

        if to_grid not in RETRO_GRIDS:
            return False
        with self._lock:
            i = self._index_of_locked(card_id)
            if i < 0:
                return False
            card = self._cards.pop(i)
            if card.grid != to_grid:
                card = replace(card, grid=to_grid)
            # Find the flat insertion point: the position of the Nth card already in
            # to_grid (clamped), so grid-local ordering is honoured.
            to_index = max(0, to_index)
            flat_pos, seen = len(self._cards), 0
            for j, c in enumerate(self._cards):
                if c.grid == to_grid:
                    if seen == to_index:
                        flat_pos = j
                        break
                    seen += 1
            self._cards.insert(flat_pos, card)
            self._revision += 1
            return True

    # ── Reactions ─────────────────────────────────────────────────────────
    #
    # Reactions are kept in a board-level map (card_id -> emoji -> {pid}) rather
    # than on the frozen RetroCard, so cards stay immutable. `pid` is the browser's
    # stable per-participant id, so one person toggling twice cancels out.

    def _card_exists_locked(self, card_id: str) -> bool:
        return any(c.id == card_id for c in self._cards)

    def toggle_reaction(self, card_id: str, emoji: str, pid: str) -> bool:
        """Toggle one participant's reaction on a card. Returns True if now set.

        Rejects (returns False) an unknown emoji, a missing card, or a blank pid —
        the emoji must be one of REACTION_EMOJIS (LAN peers are untrusted).
        """
        if emoji not in REACTION_EMOJIS or not pid:
            return False
        with self._lock:
            if not self._card_exists_locked(card_id):
                return False
            by_emoji = self._reactions.setdefault(card_id, {})
            pids = by_emoji.setdefault(emoji, set())
            if pid in pids:
                pids.discard(pid)
                now_set = False
            else:
                pids.add(pid)
                now_set = True
                # Queue a broadcast event so every poller floats this emoji once.
                self._reaction_events.append({"id": self._reaction_seq, "emoji": emoji})
                self._reaction_seq += 1
            if not pids:  # keep the map tidy
                by_emoji.pop(emoji, None)
            self._revision += 1
            return now_set

    def _reaction_counts_locked(self, card_id: str) -> dict[str, int]:
        by_emoji = self._reactions.get(card_id, {})
        # Preserve REACTION_EMOJIS order and drop empties.
        return {e: len(by_emoji[e]) for e in REACTION_EMOJIS if by_emoji.get(e)}

    def reaction_counts(self, card_id: str) -> dict[str, int]:
        """Return ``{emoji: count}`` for a card (empty if none)."""
        with self._lock:
            return self._reaction_counts_locked(card_id)

    # ── Presence & typing ─────────────────────────────────────────────────

    def heartbeat(self, pid: str, *, name: str = "", avatar: str = "", typing_grid: str = "") -> None:
        """Record that a participant is here (and optionally typing in a grid).

        Called on the browser's ~1 s tick. Ephemeral — never persisted. Does NOT
        bump ``_revision`` (it fires constantly and would defeat change-detection).
        """
        if not pid:
            return
        avatar = avatar if avatar in AVATARS else ""
        typing_grid = typing_grid if typing_grid in RETRO_GRIDS else ""
        with self._lock:
            self._presence[pid] = {
                "name": (name or "anon").strip()[:_MAX_AUTHOR] or "anon",
                "avatar": avatar,
                "typing_grid": typing_grid,
                "last_seen": time.monotonic(),
            }

    def _active_presence_locked(self) -> list[dict]:
        cutoff = time.monotonic() - _PRESENCE_TTL
        return [p for p in self._presence.values() if p["last_seen"] >= cutoff]

    def presence_list(self) -> list[dict]:
        """Return ``[{name, avatar}, …]`` for participants seen within the TTL."""
        with self._lock:
            return [{"name": p["name"], "avatar": p["avatar"]} for p in self._active_presence_locked()]

    def typing_list(self) -> list[dict]:
        """Return ``[{name, grid}, …]`` for participants currently typing."""
        with self._lock:
            return [
                {"name": p["name"], "grid": p["typing_grid"]}
                for p in self._active_presence_locked()
                if p["typing_grid"]
            ]

    # ── Shared timer ──────────────────────────────────────────────────────

    def start_timer(self, seconds: int) -> None:
        """Start a shared countdown of ``seconds`` (clamped 1..3600)."""
        seconds = max(1, min(int(seconds or 0), _MAX_TIMER))
        with self._lock:
            self._timer = {"running": True, "end_epoch": time.time() + seconds, "duration": seconds}
            self._revision += 1

    def stop_timer(self) -> None:
        """Stop/clear the shared countdown."""
        with self._lock:
            self._timer = {"running": False, "end_epoch": None, "duration": 0}
            self._revision += 1

    def _timer_locked(self) -> dict:
        # Include the server clock so clients can compute an offset and tick locally.
        return {**self._timer, "now_epoch": time.time()}

    # ── Unified live snapshot (the browser's poll payload) ─────────────────

    def state_snapshot(self, viewer_pid: str = "") -> dict:
        """Return the full live state for the browser poll in one atomic payload.

        Shape: ``{revision, cards:[{…, reactions:{emoji:count}, mine:bool}],
        presence:[…], typing:[…], timer:{running, end_epoch, now_epoch, duration}}``.
        ``mine`` is True when ``viewer_pid`` owns the card (drives the ✎/✕ controls);
        raw owner pids are never put on the wire. Built under the lock (plain
        dict/list assembly only — the JSON dump happens in the server, outside it).
        """
        from dataclasses import asdict

        with self._lock:
            cards = [
                {
                    **asdict(c),
                    "reactions": self._reaction_counts_locked(c.id),
                    "mine": bool(viewer_pid) and self._card_owner.get(c.id) == viewer_pid,
                }
                for c in self._cards
            ]
            presence = [{"name": p["name"], "avatar": p["avatar"]} for p in self._active_presence_locked()]
            typing = [
                {"name": p["name"], "grid": p["typing_grid"]}
                for p in self._active_presence_locked()
                if p["typing_grid"]
            ]
            return {
                "revision": self._revision,
                "cards": cards,
                "presence": presence,
                "typing": typing,
                "timer": self._timer_locked(),
                "reaction_events": list(self._reaction_events),
            }


def board_to_report(board: RetroBoard, *, sprint_name: str = "", today: date | None = None) -> RetroReport:
    """Snapshot a live board into a frozen, persistable RetroReport.

    Live reactions (kept in the board's own map) are folded into each frozen
    RetroCard's ``reactions`` field here, so the report/export/AI see them.
    """
    _, cards = board.snapshot()
    # Attach current reaction counts to each card (frozen — rebuild via replace).
    from dataclasses import replace

    cards = [replace(c, reactions=tuple(board.reaction_counts(c.id).items())) for c in cards]
    # Participants = distinct human authors (exclude AI-generated action items).
    seen: list[str] = []
    for c in cards:
        if c.origin == "web" and c.author and c.author not in seen:
            seen.append(c.author)
    return RetroReport(
        date=(today or date.today()).isoformat(),
        session_id=board.session_id,
        project_name=board.project_name,
        sprint_name=sprint_name or board.sprint_name,
        cards=tuple(cards),
        participants=tuple(seen),
        generated_at=_now_iso(),
    )
