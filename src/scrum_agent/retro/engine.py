"""Retro engine — the one LLM call that turns retro cards into action items.

Like the standup engine, this is a standalone helper (NOT a LangGraph node): it
calls ``get_llm()`` directly and follows the same **parse → fallback** convention
the graph nodes use (agent/nodes.py). The team fills the "What didn't go well"
grid; this reads those cards (plus "What went well" for context) and appends
AI-suggested action items to the board's "Action items" grid.

An LLM auth/billing error is NOT re-raised — it is turned into a user-facing
status message and the deterministic fallback is used, so the retro never
crashes over a missing key (same policy as standup/engine.py).

# See README: "The ReAct Loop" — using the LLM outside the main graph
# See README: "Prompt Construction" — the retro action-items prompt
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage

from scrum_agent.retro.board import RetroBoard

logger = logging.getLogger(__name__)


def _parse_action_items(raw: str) -> list[str]:
    """Extract the action-item list from an LLM response, tolerating markdown fences."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("retro: could not parse LLM JSON response")
        return []
    items = parsed.get("action_items", []) if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []
    return [str(x).strip() for x in items if str(x).strip()]


def _build_fallback_action_items(didnt_go_well: list[str]) -> list[str]:
    """Deterministic action items when the LLM is unavailable.

    Turns each problem card into a plain "Address: <problem>" follow-up so the
    grid is never left empty just because AI is offline.
    """
    return [f"Address: {p}" for p in didnt_go_well[:6] if p.strip()]


def generate_action_items(board: RetroBoard) -> str:
    """Generate action items from the board's feedback and append them (origin="ai").

    Returns a short human-facing status message for the TUI (never raises).
    """
    grids = board.cards_by_grid()

    def _annotate(card) -> str:
        # Tag a card with its total reactions so the AI can weight team sentiment.
        total = sum(board.reaction_counts(card.id).values())
        return f"{card.text}  [{total} reactions]" if total else card.text

    # Raw text drives the deterministic fallback; reaction-annotated text drives the LLM.
    didnt_raw = [c.text for c in grids.get("didnt_go_well", [])]
    didnt = [_annotate(c) for c in grids.get("didnt_go_well", [])]
    went = [_annotate(c) for c in grids.get("went_well", [])]

    if not didnt and not went:
        logger.info("retro: no feedback cards yet — nothing to generate")
        return "Add some cards first — no feedback to work from yet."

    logger.info("retro: generating action items from %d problem / %d positive card(s)", len(didnt), len(went))

    from scrum_agent.config import is_llm_configured

    configured, why = is_llm_configured()
    if not configured:
        logger.warning("retro: LLM not configured (%s) — using deterministic fallback", why)
        added = board.add_ai_cards(_build_fallback_action_items(didnt_raw))
        return f"AI unavailable ({why}) — added {added} basic action item(s)."

    from scrum_agent.agent.llm import get_llm, track_usage
    from scrum_agent.agent.nodes import _is_llm_auth_or_billing_error
    from scrum_agent.prompts.retro import get_retro_action_items_prompt

    prompt = get_retro_action_items_prompt(went_well=went, didnt_go_well=didnt)
    try:
        response = get_llm(temperature=0.2).invoke([HumanMessage(content=prompt)])
        track_usage(response)
        items = _parse_action_items(response.content)
    except Exception as exc:
        if _is_llm_auth_or_billing_error(exc):
            logger.warning("retro: LLM auth/billing error — surfacing as warning: %s", exc)
            added = board.add_ai_cards(_build_fallback_action_items(didnt_raw))
            return f"AI unavailable (API key/billing) — added {added} basic action item(s)."
        logger.warning("retro: LLM request failed, using fallback: %s", exc)
        added = board.add_ai_cards(_build_fallback_action_items(didnt_raw))
        return f"AI request failed — added {added} basic action item(s) (see logs)."

    if not items:
        added = board.add_ai_cards(_build_fallback_action_items(didnt_raw))
        return f"AI returned nothing usable — added {added} basic action item(s)."

    added = board.add_ai_cards(items)
    logger.info("retro: added %d AI action item(s)", added)
    return f"Generated {added} action item(s) from the team's feedback."
