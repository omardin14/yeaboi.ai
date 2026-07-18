"""Background PyPI update check — fire-and-forget, never blocks or crashes the app.

Mirrors the telemetry pattern (``telemetry.send_telemetry``): stdlib ``urllib``
with a short timeout, every error swallowed at debug level. The check runs once
per process on a daemon thread; the TUI polls :func:`get_update_status` each
frame to render the bottom-left version hint on the mode-select screen.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/yeaboi/json"

# Written by the daemon worker thread, read by the render thread. Single-key
# dict writes are atomic under the GIL, so no lock is needed.
_state: dict = {"latest": "", "checked": False}
_started = False


def parse_version(version: str) -> tuple[int, ...] | None:
    """Parse ``X.Y.Z``-style strings into a comparable int tuple.

    Local suffixes (``0.0.0+dev``) are stripped; each dot component keeps only
    its leading digit run (``2.10.0rc1`` -> ``(2, 10, 0)``). Returns ``None``
    when the first component has no digits — callers treat unparseable versions
    conservatively (never flag an update).
    """
    if not version:
        return None
    parts = version.split("+", 1)[0].split(".")
    numbers: list[int] = []
    for part in parts:
        match = re.match(r"\d+", part.strip())
        if match is None:
            break
        numbers.append(int(match.group()))
    return tuple(numbers) if numbers else None


def is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is strictly newer than ``current``; False when unsure."""
    latest_t = parse_version(latest)
    current_t = parse_version(current)
    if latest_t is None or current_t is None:
        return False
    return latest_t > current_t


def detect_upgrade_command() -> str:
    """Best-effort detection of how yeaboi was installed (uv tool vs pipx).

    uv tool venvs live under ``~/.local/share/uv/tools/``; pipx venvs under
    ``~/.local/pipx/venvs/``. Falls back to the documented uv install method.
    """
    try:
        exe = Path(sys.executable).resolve().as_posix()
    except OSError:
        exe = sys.executable or ""
    if "/pipx/venvs/" in exe:
        return "pipx upgrade yeaboi"
    return "uv tool upgrade yeaboi"


def fetch_latest_version(timeout: float = 3.0) -> str | None:
    """Fetch the latest released version from PyPI; None on any failure."""
    try:
        req = urllib.request.Request(_PYPI_URL, headers={"Accept": "application/json"})  # noqa: S310 - fixed https PyPI constant
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https PyPI constant
            data = json.loads(resp.read().decode("utf-8"))
        version = data["info"]["version"]
        return version if isinstance(version, str) else None
    except Exception:
        # Never let the update check crash or nag — offline is a normal state.
        logger.debug("update check failed (this is fine)", exc_info=True)
        return None


def _current_version() -> str:
    from yeaboi import __version__

    return __version__


def start_background_check() -> None:
    """Spawn the one-shot PyPI check on a daemon thread (idempotent)."""
    global _started
    if _started:
        return
    current = _current_version()
    if current == "0.0.0+dev":
        logger.info("update check skipped: running from source tree (dev version)")
        _started = True
        return

    def _worker() -> None:
        latest = fetch_latest_version()
        if latest:
            _state["latest"] = latest
            if is_newer(latest, current):
                logger.info("update available: %s -> %s", current, latest)
            else:
                logger.info("yeaboi is up to date (%s)", current)
        _state["checked"] = True

    _started = True
    logger.info("update check started (current version %s)", current)
    threading.Thread(target=_worker, name="update-check", daemon=True).start()


def get_update_status() -> dict:
    """Snapshot of the update check for the UI (and the test monkeypatch seam)."""
    current = _current_version()
    latest = _state["latest"]
    return {
        "current": current,
        "latest": latest,
        "update_available": bool(latest) and is_newer(latest, current),
        "upgrade_command": detect_upgrade_command(),
        "is_dev": current == "0.0.0+dev",
    }
