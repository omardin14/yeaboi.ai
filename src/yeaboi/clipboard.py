"""OS clipboard image reader — powers Ctrl+V screenshot paste in TUI textboxes.

Terminals cannot deliver image bytes through stdin: bracketed paste (see
``ui/shared/_input.py``) is text-only, and Cmd+V on macOS is intercepted by the
terminal emulator as a plain-text paste. So, like Claude Code, we bind **Ctrl+V**
and read the image straight off the OS clipboard by shelling out to
platform-native helpers — no new Python dependency, mirroring the external-binary
pattern of :mod:`yeaboi.voice` and :mod:`yeaboi.music`.

Design notes / architectural decisions:
- **Stdlib only.** macOS ships ``osascript``; Linux desktops usually have
  ``wl-paste`` (Wayland) or ``xclip`` (X11). We probe with ``shutil.which`` and
  degrade gracefully — a missing helper or an imageless clipboard returns ``None``,
  never raises into the TUI frame loop.
- **pngpaste fast path.** ``osascript`` round-trips the image as a hex dump
  (a 5 MB screenshot becomes ~10 MB of hex), which can take 0.5–2 s. If the user
  has `pngpaste` installed (``brew install pngpaste``) we use it instead — it
  writes raw PNG bytes to stdout in milliseconds.
- **PNG first, JPEG second.** macOS screenshots land on the clipboard as
  ``«class PNGf»``; images copied from browsers/Photos may only offer
  ``«class JPEG»``. We try both and report the mime type to the caller so the
  right extension and LLM ``mime_type`` are used. Files copied in Finder
  (``furl``) are deliberately not supported in v1.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

# Hard ceiling on how long any clipboard helper may run — a wedged osascript must
# never freeze the TUI for more than this.
_TIMEOUT_SECONDS = 10


def read_clipboard_image() -> tuple[bytes, str] | None:
    """Return ``(image_bytes, mime_type)`` from the OS clipboard, or ``None``.

    ``mime_type`` is ``"image/png"`` or ``"image/jpeg"``. Returns ``None`` when the
    clipboard holds no image, the platform helpers are missing, or anything goes
    wrong — callers show a "No image on clipboard" notice and move on.
    """
    try:
        if sys.platform == "darwin":
            result = _read_macos_clipboard()
        elif sys.platform.startswith("linux"):
            result = _read_linux_clipboard()
        else:
            logger.warning("clipboard image paste unsupported on platform: %s", sys.platform)
            return None
    except Exception as exc:  # defensive: clipboard access must never crash the TUI
        logger.warning("clipboard image read failed: %s", exc)
        return None

    if result:
        data, mime = result
        logger.info("clipboard image read: %d bytes (%s)", len(data), mime)
    else:
        logger.info("no image found on clipboard")
    return result


def _run(cmd: list[str]) -> subprocess.CompletedProcess | None:
    """Run a clipboard helper, returning None on timeout/missing binary."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("clipboard helper %s failed: %s", cmd[0], exc)
        return None


def _read_macos_clipboard() -> tuple[bytes, str] | None:
    """Read an image from the macOS clipboard via pngpaste (fast) or osascript."""
    # Fast path: pngpaste writes raw PNG bytes to stdout ("-" = stdout).
    if shutil.which("pngpaste"):
        proc = _run(["pngpaste", "-"])
        if proc and proc.returncode == 0 and proc.stdout:
            return proc.stdout, "image/png"

    # osascript coerces the clipboard to a typed data blob rendered as
    # «data PNGf<hex>» on stdout; a non-image clipboard makes the coercion fail
    # with a non-zero exit ("Can't make some data into the expected type").
    for cls, mime in (("PNGf", "image/png"), ("JPEG", "image/jpeg")):
        proc = _run(["osascript", "-e", f"the clipboard as «class {cls}»"])
        if not proc or proc.returncode != 0:
            continue
        # osascript prints the guillemet-wrapped hex dump in UTF-8 («data PNGf…»).
        data = _parse_osascript_hex(proc.stdout.decode("utf-8", errors="replace"), cls)
        if data:
            return data, mime
    return None


def _parse_osascript_hex(out: str, cls: str) -> bytes | None:
    """Decode osascript's ``«data PNGf89504E47...»`` hex dump into raw bytes."""
    out = out.strip()
    prefix = f"«data {cls}"
    if not (out.startswith(prefix) and out.endswith("»")):
        return None
    hex_str = out[len(prefix) : -1].strip()
    try:
        return bytes.fromhex(hex_str) or None
    except ValueError:
        logger.warning("could not decode osascript clipboard hex (%d chars)", len(hex_str))
        return None


def _read_linux_clipboard() -> tuple[bytes, str] | None:
    """Read an image from the Linux clipboard via wl-paste (Wayland) or xclip (X11)."""
    candidates = [
        (["wl-paste", "--type", "image/png"], "image/png"),
        (["xclip", "-selection", "clipboard", "-t", "image/png", "-o"], "image/png"),
    ]
    for cmd, mime in candidates:
        if not shutil.which(cmd[0]):
            continue
        proc = _run(cmd)
        if proc and proc.returncode == 0 and proc.stdout:
            return proc.stdout, mime
    return None
