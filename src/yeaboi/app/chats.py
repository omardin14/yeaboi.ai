"""Live planning conversations — one :class:`ChatSession` per session id.

Sessions live in the backend, not in the renderer: a reloaded window rejoins
the conversation it left, and the graph is compiled once for the process
rather than once per turn. Persistence is the shared session store
(``sessions.py``), the same rows ``plan_get``/``plan_export``/``plan_sync``
and the recent-sessions list read — a plan started here is one plan
everywhere. Conversations the old file store holds still open, read-only.

The graph factory, loader, saver and version recorder are injected so the
whole surface can be tested without an LLM or a home directory.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from yeaboi.agent.chat_session import ChatSession, last_completed_node, start_state

logger = logging.getLogger(__name__)


@dataclass
class LiveChat:
    """One conversation plus the lock that keeps its turns single-file."""

    session_id: str
    session: ChatSession
    turn: threading.Lock = field(default_factory=threading.Lock)
    title: str = ""  # a user-given title, written with the first save


def _compile_graph():
    from yeaboi.agent.graph import create_graph

    return create_graph()


def _store():
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    return SessionStore(get_db_path())


def _load(session_id: str) -> dict | None:
    with _store() as store:
        state = store.load_state(session_id)
    if state is not None:
        return state
    # A conversation from before the store move. Read-only: its next save
    # lands in the store, where every other reader already looks.
    from yeaboi.persistence import load_graph_state

    return load_graph_state(session_id)


def _save(session_id: str, state: dict) -> None:
    with _store() as store:
        store.create_session(session_id, mode="planning")  # INSERT OR IGNORE — adopts a file-store chat
        store.save_state(session_id, state)
        analysis = state.get("project_analysis")
        name = getattr(analysis, "project_name", "") or ""
        if name:
            store.update_project_name(session_id, name)
        node = last_completed_node(state)
        if node:
            store.update_last_node(session_id, node)


def _save_meta(session_id: str, *, title: str) -> None:
    with _store() as store:
        store.update_session_meta(session_id, title=title)


def _record_version(session_id: str, section: str, payload: dict) -> int:
    with _store() as store:
        return store.record_plan_version(session_id, section, payload)


def _new_id() -> str:
    from yeaboi.sessions import make_session_id

    return make_session_id()


class UnknownChatError(LookupError):
    """No conversation with that id is open or stored."""


class ChatSupervisor:
    """The open conversations. Thread-safe; one compiled graph for all of them."""

    def __init__(
        self,
        *,
        graph_factory=_compile_graph,
        loader=_load,
        saver=_save,
        id_factory=_new_id,
        meta_saver: Callable[..., None] = _save_meta,
        version_recorder: Callable[[str, str, dict], int] = _record_version,
    ) -> None:
        self._graph_factory = graph_factory
        self._loader = loader
        self._saver = saver
        self._id_factory = id_factory
        self._meta_saver = meta_saver
        self._version_recorder = version_recorder
        self._chats: dict[str, LiveChat] = {}
        self._lock = threading.Lock()
        self._graph = None
        self._graph_lock = threading.Lock()

    def graph(self):
        """The compiled planning graph — built once, on first use."""
        with self._graph_lock:
            if self._graph is None:
                logger.info("Compiling the planning graph for the app")
                self._graph = self._graph_factory()
            return self._graph

    def _session(self, session_id: str, state: dict) -> ChatSession:
        # No typewriter: a socket wants the reply once, from the state, not
        # paced eight characters at a time.
        return ChatSession(
            self.graph(),
            state,
            typewriter=False,
            on_version=partial(self._version_recorder, session_id),
        )

    def create(
        self,
        description: str,
        *,
        intake_mode: str = "",
        solo: bool = False,
        analysis_profile_id: str = "",
        context_scope: dict | None = None,
        project_label: str = "",
        title: str = "",
    ) -> LiveChat:
        """Open a new conversation seeded with the greeting and the description."""
        session_id = self._id_factory()
        state = start_state(
            description,
            intake_mode=intake_mode,
            solo=solo,
            analysis_profile_id=analysis_profile_id,
            context_scope=context_scope,
            project_label=project_label,
        )
        chat = LiveChat(session_id, self._session(session_id, state), title=title)
        with self._lock:
            self._chats[session_id] = chat
        logger.info("Chat created: session=%s", session_id)
        return chat

    def open(self, session_id: str) -> LiveChat:
        """The live conversation for an id, resuming it from disk if needed."""
        with self._lock:
            chat = self._chats.get(session_id)
            if chat is not None:
                return chat
        state = self._loader(session_id)
        if state is None:
            raise UnknownChatError(session_id)
        chat = LiveChat(session_id, self._session(session_id, state))
        with self._lock:
            # Another thread may have resumed the same id first — one live
            # session per conversation, or two turns would fork the state.
            chat = self._chats.setdefault(session_id, chat)
        logger.info("Chat resumed: session=%s", session_id)
        return chat

    def save(self, chat: LiveChat) -> None:
        self._saver(chat.session_id, chat.session.state)
        if chat.title:
            # After the state, so the row exists; once, so a later rename sticks.
            self._meta_saver(chat.session_id, title=chat.title)
            chat.title = ""

    def close(self, session_id: str) -> None:
        """Forget a conversation (it stays on disk and can be reopened)."""
        with self._lock:
            self._chats.pop(session_id, None)

    def close_all(self) -> None:
        with self._lock:
            self._chats.clear()
