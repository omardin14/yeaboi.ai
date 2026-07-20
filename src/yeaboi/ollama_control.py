"""Controlling the local Ollama server from the app (stop-on-exit).

yeaboi never *starts* the Ollama server — the user does (typically
``brew services start ollama`` or ``ollama serve``) — so "stopping" it is a
best-effort courtesy offered when quitting the TUI:

- brew-managed server → ``brew services stop ollama`` (full stop, RAM freed)
- anything else → ask Ollama to unload the model (``keep_alive: 0``), which
  frees the model's RAM/VRAM while the (near-idle) server keeps running.

Every function here is never-raising: quitting the app must not be blocked by
a broken brew install or an unreachable server.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Bounded timeouts so quitting never stalls: the reachability probe runs on
# every ollama-provider exit, the stop commands only after the user says yes.
_PROBE_TIMEOUT = 2
_BREW_INFO_TIMEOUT = 10
_BREW_STOP_TIMEOUT = 15
_UNLOAD_TIMEOUT = 10


def _is_localhost(base_url: str) -> bool:
    """True when the Ollama base URL points at this machine (only then is the
    server plausibly ours to stop)."""
    try:
        host = urlparse(base_url).hostname
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


def should_offer_ollama_stop() -> bool:
    """Gate for the exit prompt: local provider + localhost URL + server up."""
    from yeaboi.config import get_llm_provider, get_ollama_base_url

    try:
        if get_llm_provider() != "ollama":
            return False
        base = get_ollama_base_url()
        if not _is_localhost(base):
            return False
        import httpx

        return httpx.get(f"{base}/api/tags", timeout=_PROBE_TIMEOUT).status_code == 200
    except Exception:
        return False


def _brew_managed() -> bool:
    """True when brew exists and reports the ollama service as started."""
    if not shutil.which("brew"):
        return False
    try:
        result = subprocess.run(  # noqa: S603 — fixed, app-chosen command
            ["brew", "services", "info", "ollama", "--json"],
            capture_output=True,
            text=True,
            timeout=_BREW_INFO_TIMEOUT,
        )
        if result.returncode != 0:
            return False
        info = json.loads(result.stdout)
        # brew emits a one-element list; parse defensively across versions.
        entry = info[0] if isinstance(info, list) and info else info
        return isinstance(entry, dict) and entry.get("status") == "started"
    except Exception:
        return False


def _unload_model() -> bool:
    """Ask Ollama to unload the configured model (keep_alive: 0) to free RAM."""
    from yeaboi.agent.llm import _PROVIDER_DEFAULTS
    from yeaboi.config import get_llm_model, get_ollama_base_url

    try:
        import httpx

        model = get_llm_model() or _PROVIDER_DEFAULTS["ollama"]
        resp = httpx.post(
            f"{get_ollama_base_url()}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=_UNLOAD_TIMEOUT,
        )
        return resp.status_code == 200
    except Exception:
        logger.warning("could not unload ollama model", exc_info=True)
        return False


def stop_ollama_server() -> tuple[bool, str]:
    """Smart stop. Returns (fully_stopped, user_message); never raises."""
    logger.info("stop_ollama_server: attempting")
    try:
        if _brew_managed():
            result = subprocess.run(  # noqa: S603 — fixed, app-chosen command
                ["brew", "services", "stop", "ollama"],
                capture_output=True,
                text=True,
                timeout=_BREW_STOP_TIMEOUT,
            )
            if result.returncode == 0:
                logger.info("stop_ollama_server: stopped via brew services")
                return True, "Ollama server stopped (brew services)"
            logger.warning("brew services stop failed (rc=%d): %s", result.returncode, result.stderr.strip()[:200])
        if _unload_model():
            logger.info("stop_ollama_server: model unloaded (server not brew-managed)")
            return False, "Model unloaded (RAM freed) — the server wasn't started by brew, stop it yourself if needed"
        return False, "Could not stop Ollama — see logs"
    except Exception:
        logger.warning("stop_ollama_server failed", exc_info=True)
        return False, "Could not stop Ollama — see logs"
