"""Unit tests for the Retro Cloudflare tunnel helper (hermetic — no network)."""

import hashlib
import platform
import stat

import pytest

from yeaboi.retro import tunnel


class _FakeResp:
    """Minimal context-manager stand-in for urllib's urlopen response."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestChecksumVerification:
    def test_matching_hash_passes(self, monkeypatch):
        data = b"legit cloudflared bytes"
        monkeypatch.setitem(tunnel._ASSET_SHA256, "asset-x", hashlib.sha256(data).hexdigest())
        tunnel._verify_sha256("asset-x", data)  # must not raise

    def test_mismatched_hash_raises(self, monkeypatch):
        monkeypatch.setitem(tunnel._ASSET_SHA256, "asset-x", "0" * 64)
        with pytest.raises(OSError, match="checksum mismatch"):
            tunnel._verify_sha256("asset-x", b"tampered")

    def test_unknown_asset_is_refused(self):
        with pytest.raises(OSError, match="no pinned checksum"):
            tunnel._verify_sha256("asset-never-pinned", b"x")

    def test_release_base_is_pinned_not_latest(self):
        assert "latest" not in tunnel._RELEASE_BASE
        assert tunnel._CLOUDFLARED_VERSION in tunnel._RELEASE_BASE


class TestDownloadIntegrity:
    def test_tampered_payload_never_lands_on_disk(self, tmp_path, monkeypatch):
        dest = tmp_path / "cloudflared"
        monkeypatch.setattr(tunnel, "_asset_name", lambda *a: ("cloudflared-linux-amd64", False))
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"malicious"))
        with pytest.raises(OSError, match="checksum mismatch"):
            tunnel._download_cloudflared(dest)
        assert not dest.exists()
        assert not dest.with_suffix(dest.suffix + ".part").exists()

    def test_valid_payload_is_installed_owner_execute_only(self, tmp_path, monkeypatch):
        dest = tmp_path / "cloudflared"
        data = b"valid-binary"
        monkeypatch.setattr(tunnel, "_asset_name", lambda *a: ("asset-ok", False))
        monkeypatch.setitem(tunnel._ASSET_SHA256, "asset-ok", hashlib.sha256(data).hexdigest())
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(data))
        out = tunnel._download_cloudflared(dest)
        assert out == dest and dest.read_bytes() == data
        mode = dest.stat().st_mode
        assert mode & stat.S_IXUSR  # owner can execute
        assert not (mode & stat.S_IXGRP) and not (mode & stat.S_IXOTH)  # group/other cannot


class TestAssetName:
    def test_darwin_arm64_is_tgz(self):
        name, is_tgz = tunnel._asset_name("Darwin", "arm64")
        assert name == "cloudflared-darwin-arm64.tgz" and is_tgz is True

    def test_linux_amd64_is_raw(self):
        name, is_tgz = tunnel._asset_name("Linux", "x86_64")
        assert name == "cloudflared-linux-amd64" and is_tgz is False

    def test_windows_amd64_exe(self):
        name, is_tgz = tunnel._asset_name("Windows", "AMD64")
        assert name == "cloudflared-windows-amd64.exe" and is_tgz is False

    def test_unsupported_platform_raises(self):
        with pytest.raises(OSError):
            tunnel._asset_name("Plan9", "sparc")


class TestUrlRegex:
    def test_matches_banner_line(self):
        line = "2026-07-10 INF |  https://calm-tree-1234.trycloudflare.com  |"
        m = tunnel._URL_RE.search(line)
        assert m and m.group(0) == "https://calm-tree-1234.trycloudflare.com"

    def test_no_match_on_unrelated(self):
        assert tunnel._URL_RE.search("registered tunnel connection") is None


class TestEnsureCloudflared:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        fake = tmp_path / "cf"
        fake.write_text("x")
        monkeypatch.setenv("CLOUDFLARED_PATH", str(fake))
        assert tunnel.ensure_cloudflared() == fake

    def test_uses_binary_on_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLOUDFLARED_PATH", raising=False)
        monkeypatch.setattr(tunnel.shutil, "which", lambda name: "/usr/local/bin/cloudflared")
        assert str(tunnel.ensure_cloudflared()) == "/usr/local/bin/cloudflared"

    def test_uses_cached_copy(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLOUDFLARED_PATH", raising=False)
        monkeypatch.setattr(tunnel.shutil, "which", lambda name: None)
        cached = tmp_path / "cloudflared"
        cached.write_text("x")
        monkeypatch.setattr(tunnel, "_cached_binary_path", lambda: cached)
        # _download_cloudflared must NOT be called when the cache exists.
        monkeypatch.setattr(tunnel, "_download_cloudflared", lambda *a, **k: pytest.fail("should not download"))
        assert tunnel.ensure_cloudflared() == cached

    def test_download_failure_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLOUDFLARED_PATH", raising=False)
        monkeypatch.setattr(tunnel.shutil, "which", lambda name: None)
        monkeypatch.setattr(tunnel, "_cached_binary_path", lambda: tmp_path / "nope")

        def _boom(*a, **k):
            raise OSError("network down")

        monkeypatch.setattr(tunnel, "_download_cloudflared", _boom)
        assert tunnel.ensure_cloudflared() is None


def _fake_cloudflared(tmp_path, *, emit_url: bool) -> "object":
    """Write a fake cloudflared shell script that mimics stderr output."""
    script = tmp_path / "cloudflared"
    if emit_url:
        body = '#!/bin/sh\necho "INF |  https://fake-tunnel-abcd.trycloudflare.com  |" >&2\nsleep 5\n'
    else:
        body = "#!/bin/sh\necho 'INF starting' >&2\nexit 0\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.skipif(platform.system() == "Windows", reason="fake sh script is POSIX-only")
class TestCloudflareTunnel:
    def test_start_returns_url_then_stops(self, tmp_path):
        binary = _fake_cloudflared(tmp_path, emit_url=True)
        t = tunnel.CloudflareTunnel(5173, binary=binary)
        url = t.start(timeout=10)
        assert url == "https://fake-tunnel-abcd.trycloudflare.com"
        assert t.public_url == url
        t.stop()
        assert t._proc is None

    def test_start_returns_none_when_no_url(self, tmp_path):
        binary = _fake_cloudflared(tmp_path, emit_url=False)
        t = tunnel.CloudflareTunnel(5173, binary=binary)
        assert t.start(timeout=5) is None

    def test_start_none_when_binary_unavailable(self, monkeypatch):
        monkeypatch.setattr(tunnel, "ensure_cloudflared", lambda: None)
        t = tunnel.CloudflareTunnel(5173)
        assert t.start(timeout=2) is None
