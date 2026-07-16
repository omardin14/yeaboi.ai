"""Optional public tunnel for the Retro board — off-network joining, zero setup.

The LAN server (retro/server.py) only reaches teammates on the same network. To
let a remote teammate join, the host can start a **Cloudflare quick tunnel**,
which exposes ``http://localhost:<port>`` at a random ``https://…trycloudflare.com``
URL. Crucially this needs **no Cloudflare account, no token, no signup** — so the
app can own the whole flow: it downloads the ``cloudflared`` binary on first use
(cached under ``~/.scrum-agent/bin/``) and runs it. (ngrok, by contrast, forces a
per-user authtoken, so it can't be truly zero-setup.)

The tunnel forwards to our existing token-gated server, so ``/api/*`` stays
protected; the public URL simply carries the same ``?token=`` the LAN URL does,
now over HTTPS. This turns the retro into "anyone with the link can join" — fine
for a retrospective, but it is internet-reachable while the tunnel is up.

Everything here is best-effort and never raises into the TUI: a failed download
or tunnel start returns ``None`` / a status string, and the retro keeps working
on the LAN.

# See README: "Retro" — remote joining via Cloudflare tunnel
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# cloudflared prints the assigned URL to stderr inside a banner box; match it anywhere.
_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

# GitHub's "latest" redirect always resolves to the newest release asset.
_RELEASE_BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download"


def _asset_name(system: str | None = None, machine: str | None = None) -> tuple[str, bool]:
    """Return (github_asset_filename, is_tgz) for the current platform.

    macOS assets ship as ``.tgz`` archives; Linux/Windows are raw binaries.
    """
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("i386", "i686", "x86"):
        arch = "386"
    else:
        arch = machine
    if system == "darwin":
        return f"cloudflared-darwin-{arch}.tgz", True
    if system == "linux":
        return f"cloudflared-linux-{arch}", False
    if system == "windows":
        return f"cloudflared-windows-{arch}.exe", False
    raise OSError(f"unsupported platform for cloudflared: {system}/{machine}")


def _cached_binary_path() -> Path:
    """Return the path where the app caches its own cloudflared binary."""
    from yeaboi.paths import get_bin_dir

    name = "cloudflared.exe" if platform.system().lower() == "windows" else "cloudflared"
    return get_bin_dir() / name


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _download_cloudflared(dest: Path, *, timeout: int = 120) -> Path:
    """Download (and extract, on macOS) the cloudflared binary to ``dest``.

    Downloads over HTTPS from the official ``cloudflare/cloudflared`` GitHub
    release. Raises on failure; the caller degrades gracefully.
    """
    import urllib.request

    asset, is_tgz = _asset_name()
    url = f"{_RELEASE_BASE}/{asset}"
    logger.info("retro: downloading cloudflared from %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - trusted GitHub host
        data = resp.read()
    if is_tgz:
        import io
        import tarfile

        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.name.endswith("cloudflared")), None)
            if member is None:
                raise OSError("cloudflared not found inside downloaded archive")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise OSError("could not extract cloudflared from archive")
            tmp.write_bytes(extracted.read())
    else:
        tmp.write_bytes(data)
    tmp.replace(dest)
    _make_executable(dest)
    logger.info("retro: cloudflared cached at %s", dest)
    return dest


def ensure_cloudflared() -> Path | None:
    """Return a path to a runnable cloudflared, downloading it on first use.

    Resolution order: ``CLOUDFLARED_PATH`` env → a ``cloudflared`` already on
    PATH → the app's cached copy → download. Returns ``None`` if it cannot be
    obtained (caller shows a status message and stays LAN-only).
    """
    override = os.getenv("CLOUDFLARED_PATH")
    if override and Path(override).exists():
        return Path(override)

    on_path = shutil.which("cloudflared")
    if on_path:
        return Path(on_path)

    cached = _cached_binary_path()
    if cached.exists():
        return cached

    try:
        return _download_cloudflared(cached)
    except Exception as e:
        logger.warning("retro: failed to obtain cloudflared: %s", e)
        return None


class CloudflareTunnel:
    """A Cloudflare quick tunnel forwarding a public HTTPS URL to a local port."""

    def __init__(self, port: int, *, binary: Path | None = None) -> None:
        self.port = port
        self._binary = binary
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._url = ""

    @property
    def public_url(self) -> str:
        return self._url

    def start(self, *, timeout: float = 30.0) -> str | None:
        """Launch cloudflared and wait up to ``timeout`` s for the public URL.

        Returns the ``https://…trycloudflare.com`` URL, or ``None`` on failure
        (binary unavailable, process died, or no URL within the timeout).
        """
        binary = self._binary or ensure_cloudflared()
        if binary is None:
            return None
        self._binary = binary

        logger.info("retro: starting cloudflare tunnel for localhost:%d", self.port)
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - fixed, app-managed binary + args
                [str(binary), "tunnel", "--no-autoupdate", "--url", f"http://localhost:{self.port}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            logger.warning("retro: could not launch cloudflared: %s", e)
            return None

        found = threading.Event()

        def _drain() -> None:
            # Keep reading stderr for the tunnel's whole life: capture the URL once,
            # then keep draining so cloudflared's pipe buffer never fills and blocks it.
            assert self._proc is not None and self._proc.stderr is not None
            for line in self._proc.stderr:
                if not self._url:
                    m = _URL_RE.search(line)
                    if m:
                        self._url = m.group(0)
                        found.set()

        self._reader = threading.Thread(target=_drain, name="retro-tunnel", daemon=True)
        self._reader.start()

        # Wait for the URL, but bail early if the process exits first.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if found.wait(timeout=0.2):
                break
            if self._proc.poll() is not None:  # cloudflared exited before emitting a URL
                logger.warning("retro: cloudflared exited early (code %s)", self._proc.returncode)
                break

        if not self._url:
            self.stop()
            return None
        logger.info("retro: tunnel ready at %s", self._url)
        return self._url

    def stop(self) -> None:
        """Terminate the tunnel process and free its resources."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as e:
            logger.debug("retro: error stopping tunnel: %s", e)
        finally:
            self._proc = None
        if self._reader:
            self._reader.join(timeout=2)
            self._reader = None
        logger.info("retro: tunnel stopped")
