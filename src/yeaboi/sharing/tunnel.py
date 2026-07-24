"""Shared Cloudflare quick-tunnel API.

The implementation remains in :mod:`yeaboi.retro.tunnel` for compatibility with
existing installations and imports. New output-sharing code imports it through
this mode-neutral module, leaving one pinned/download-verified implementation.
"""

from yeaboi.retro.tunnel import CloudflareTunnel, ensure_cloudflared

__all__ = ["CloudflareTunnel", "ensure_cloudflared"]
