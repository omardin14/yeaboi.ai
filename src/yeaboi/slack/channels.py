"""The workspace's channels, so a channel is chosen rather than typed.

``SLACK_CHANNEL_ID`` is an opaque id a person otherwise has to hunt for in the
Slack client and paste correctly. This reads the roster so a surface can offer
it as a list.

Deliberately not an ``engine.py``: ``test_surface_parity`` force-registers
every public name in one, and a picker's data source is not a capability.

:func:`list_channels` never raises. Every reason it cannot answer — no token,
a missing scope, a rate limit — comes back as ``reason``, because a settings
page that offers a text box and an explanation is useful and one that 500s is
not.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: ~2000 channels. A workspace larger than this pages out with a reason rather
#: than following a cursor forever on a settings-page render.
MAX_PAGES = 10

#: Everything the bot can see, and the fallback when it cannot see private ones.
PRIVATE_TYPES = "public_channel,private_channel"
PUBLIC_TYPES = "public_channel"


def list_channels() -> dict:
    """``{"channels": [{id, name, is_private}], "reason": str}``.

    A non-empty ``reason`` beside a non-empty list means the list is partial.
    """
    from yeaboi.tools import slack

    if not slack._token():
        return {
            "channels": [],
            "reason": "No Slack bot token — save SLACK_BOT_TOKEN under Settings ▸ Credentials.",
        }

    budget = slack.RetryBudget()

    def _list(types: str):
        return slack.paginate(
            lambda cursor: slack.conversations_list(cursor=cursor, types=types, budget=budget),
            "channels",
            max_pages=MAX_PAGES,
        )

    items, error = _list(PRIVATE_TYPES)
    if error == "missing_scope":
        # Slack fails the WHOLE call when the token lacks groups:read, so asking
        # for private channels costs the public ones too. Most of what they
        # wanted beats nothing, which is this module's whole posture.
        items, error = _list(PUBLIC_TYPES)
    channels = [
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "is_private": bool(item.get("is_private")),
        }
        for item in items
        # exclude_archived is asked for; this is what makes it true regardless.
        if item.get("id") and not item.get("is_archived")
    ]
    channels.sort(key=lambda c: c["name"])
    reason = ""
    if error:
        reason = slack.error_message(slack.SlackResponse(ok=False, error=error))
    elif len(items) >= MAX_PAGES * 200:
        reason = "Showing the first few thousand channels — search for the one you want."
    logger.info("slack: listed %d channel(s)", len(channels))
    return {"channels": channels, "reason": reason}
