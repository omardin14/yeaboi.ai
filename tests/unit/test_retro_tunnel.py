"""Unit tests for the Retro Cloudflare tunnel helper (hermetic — no network)."""

import platform
import stat

import pytest

from yeaboi.retro import tunnel


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
