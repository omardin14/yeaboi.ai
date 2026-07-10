"""Retro mode — a collaborative sprint retrospective board.

A retro's value is the whole team contributing. The app runs locally, so the host
starts a retro and this subsystem spins up a small LAN web server (stdlib only);
teammates open the printed share code / URL in any browser and add sticky cards
to four grids (What went well / What didn't go well / Action items / Demos) in
real time. The host can then generate AI action items from the feedback and
export a Markdown + HTML summary.

# See README: "Retro" — board, LAN server, AI action items, export

Public API is re-exported here so callers can import the common pieces without
knowing the module layout. The mutable ``RetroBoard`` and the frozen artifacts
(``RetroCard`` / ``RetroReport`` in agent/state.py) are the core types.
"""

from scrum_agent.retro.board import RetroBoard, board_to_report
from scrum_agent.retro.server import RetroServer
from scrum_agent.retro.store import RetroStore
from scrum_agent.retro.tunnel import CloudflareTunnel, ensure_cloudflared

__all__ = [
    "CloudflareTunnel",
    "RetroBoard",
    "RetroServer",
    "RetroStore",
    "board_to_report",
    "ensure_cloudflared",
]
