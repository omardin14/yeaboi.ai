"""Notion (Docs) phase of the provider selection wizard.

# See README: "Architecture" — this module handles the standalone Notion
# credential step. Unlike Confluence (which rides on Jira's Atlassian auth in the
# Issue Tracking form), Notion is an independent doc tool with its own integration
# token, so it gets its own optional wizard step.
#
# It reuses the generic multi-field form renderer (_build_issue_tracking_screen,
# which accepts `fields=` and `subtitle=`) and the same pulsing verify/confirm
# animation as the Jira/AzDO form — just with _NOTION_FIELDS and a live
# _verify_notion check.
"""

from __future__ import annotations

import math
import sys
import termios
import time
import tty

from rich.console import Console
from rich.live import Live

from scrum_agent.ui.provider_select._config import _save_progress
from scrum_agent.ui.provider_select._constants import _NOTION_FIELDS
from scrum_agent.ui.provider_select._verification import _verify_notion
from scrum_agent.ui.provider_select.screens._screens_vc import _build_issue_tracking_screen
from scrum_agent.ui.shared._animations import FRAME_TIME_30FPS

_SUBTITLE = "Docs / Notion"


def _run_notion(
    console: Console,
    read_key,
    existing_config: dict[str, str] | None,
    live: Live,
) -> dict[str, str] | None:
    """Show the optional Notion credential form and verify the token.

    Returns a dict of collected Notion env vars (empty dict when the user skips by
    pressing Enter with no token), or None when the user presses Esc to go back.
    Because Notion is optional, an empty token is a valid "skip" — the step never
    blocks users who don't use Notion.
    """
    import threading

    fields = _NOTION_FIELDS
    n = len(fields)
    _cfg = existing_config or {}
    values: dict[int, str] = {i: _cfg.get(field["env_var"], "") for i, field in enumerate(fields)}
    errors: dict[int, str] = {}
    verified: dict[int, bool] = {}
    selected = 0

    # Drain any buffered stdin so a held key from the previous screen doesn't leak in.
    import select as _sel

    _drain_fd = sys.stdin.fileno()
    _drain_old = termios.tcgetattr(_drain_fd)
    try:
        tty.setcbreak(_drain_fd)
        while _sel.select([_drain_fd], [], [], 0.05)[0]:
            sys.stdin.read(1)
    finally:
        termios.tcsetattr(_drain_fd, termios.TCSADRAIN, _drain_old)

    def _render(**kw) -> None:
        w, h = console.size
        live.update(
            _build_issue_tracking_screen(
                selected,
                values,
                width=w,
                height=h,
                fields=fields,
                subtitle=_SUBTITLE,
                **kw,
            )
        )

    _render()

    while True:
        key = read_key()

        if key in ("up", "scroll_up"):
            selected = (selected - 1) % n
        elif key in ("down", "scroll_down"):
            selected = (selected + 1) % n
        elif key == "enter":
            token = values.get(0, "").strip()

            # Empty token → skip Notion entirely (it's optional).
            if not token:
                return {}

            # Verify the token with a pulsing border while the API call runs.
            verify_result: list[tuple[bool, str]] = []

            def _do_verify():
                verify_result.append(_verify_notion(token))

            thread = threading.Thread(target=_do_verify, daemon=True)
            thread.start()

            pulse_start = time.monotonic()
            while thread.is_alive():
                elapsed = time.monotonic() - pulse_start
                intensity = (math.sin(elapsed * 6) + 1) / 2
                v = int(60 + 140 * intensity)
                _render(border_overrides={i: f"rgb({v},{v},{v})" for i in range(n)})
                time.sleep(FRAME_TIME_30FPS)

            thread.join()
            ok, msg = verify_result[0]

            if ok:
                # Green success flash, matching the Jira/VC verify animation.
                green_r, green_g, green_b = 80, 220, 120
                for frame in range(10):
                    t = frame / 9
                    intensity = math.sin(t * math.pi)
                    r = int(green_r + (255 - green_r) * intensity)
                    g = int(green_g + (255 - green_g) * intensity)
                    b = int(green_b + (255 - green_b) * intensity)
                    _render(
                        verified={i: True for i in range(n)},
                        border_overrides={i: f"rgb({r},{g},{b})" for i in range(n)},
                    )
                    time.sleep(FRAME_TIME_30FPS)
                _render(verified={i: True for i in range(n)})
                time.sleep(0.6)

                notion_data = {}
                for i, field in enumerate(fields):
                    val = values.get(i, "").strip()
                    if val:
                        notion_data[field["env_var"]] = val
                _save_progress(notion_data)
                return notion_data

            # Verification failed — surface the error on the token field.
            errors[0] = msg
            selected = 0
            _render(errors=errors)
            continue

        elif key == "esc":
            return None
        elif key == "clear":
            values[selected] = ""
            errors.pop(selected, None)
            verified.pop(selected, None)
        elif key == "backspace":
            values[selected] = values[selected][:-1]
            errors.pop(selected, None)
            verified.pop(selected, None)
        elif key == "tab":
            selected = (selected + 1) % n
        elif key.startswith("paste:"):
            values[selected] = values.get(selected, "") + key[6:]
            errors.pop(selected, None)
            verified.pop(selected, None)
        elif len(key) == 1 and key.isprintable():
            values[selected] = values.get(selected, "") + key
            errors.pop(selected, None)
            verified.pop(selected, None)

        _render(errors=errors, verified=verified)
