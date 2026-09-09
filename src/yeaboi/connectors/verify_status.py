"""What the last live probe of each connection said, and whether it still holds.

``registry.is_connected`` answers "are the credentials present". That is not the
same question as "do they work", and a surface that paints one as the other
calls a typo connected. This module holds the second answer: the outcome of the
last :func:`yeaboi.settings.engine.verify_connection` for a kind, so a chip can
say ``key saved`` until something has actually checked.

Two rules keep it honest:

- **No credential, and no digest of one.** A row records which envs the check
  ran against and whether each was non-empty at the time — never a value.
- **A stored outcome expires on change, not on age.** Editing a credential
  drops its row back to ``untested`` (:func:`forget_for_env` on every write,
  and the recorded presence map catches a hand-edited ``.env``). Elapsed time
  alone changes nothing: the row carries ``checked_at`` and the surface words it.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FILE_VERSION = 1

#: Never probed, or probed before a credential it depends on changed.
OUTCOME_UNTESTED = "untested"
#: The vendor answered and accepted the credentials.
OUTCOME_OK = "ok"
#: The vendor answered and refused them.
OUTCOME_FAILED = "failed"


@dataclass(frozen=True)
class VerifyStatus:
    """One connection's last probe. ``envs_present`` is a presence map, not values."""

    outcome: str = OUTCOME_UNTESTED
    message: str = ""
    checked_at: str = ""
    envs_present: dict[str, bool] = field(default_factory=dict)


UNTESTED = VerifyStatus()

_cache: dict = {"mtime": None, "rows": {}}


def _store_path():
    from yeaboi import paths

    return paths.get_connection_status_path()


def invalidate() -> None:
    """Drop the read cache. For tests and for a data-dir move."""
    _cache.update({"mtime": None, "rows": {}})


def _presence(envs) -> dict[str, bool]:
    return {env: bool(os.environ.get(env, "").strip()) for env in envs}


def _load() -> dict[str, VerifyStatus]:
    """Every stored row, tolerant of a damaged file.

    A malformed file is a warning and an empty store, never a crash — a settings
    page must render with no status rather than not at all.
    """
    path = _store_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache["mtime"] == mtime:
        return _cache["rows"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("connection status: %s is unreadable — ignoring it", path.name)
        return {}
    if not isinstance(raw, dict) or raw.get("version") != FILE_VERSION:
        logger.warning("connection status: %s has an unknown shape — ignoring it", path.name)
        return {}
    rows: dict[str, VerifyStatus] = {}
    for key, entry in (raw.get("connections") or {}).items():
        if not isinstance(entry, dict) or entry.get("outcome") not in (OUTCOME_OK, OUTCOME_FAILED):
            continue
        presence = entry.get("envs_present")
        rows[str(key)] = VerifyStatus(
            outcome=str(entry["outcome"]),
            message=str(entry.get("message", "")),
            checked_at=str(entry.get("checked_at", "")),
            envs_present={str(k): bool(v) for k, v in presence.items()} if isinstance(presence, dict) else {},
        )
    _cache.update({"mtime": mtime, "rows": rows})
    return rows


def _write(rows: dict[str, VerifyStatus]) -> None:
    path = _store_path()
    payload = {
        "version": FILE_VERSION,
        "connections": {
            key: {
                "outcome": row.outcome,
                "message": row.message,
                "checked_at": row.checked_at,
                "envs_present": dict(row.envs_present),
            }
            for key, row in sorted(rows.items())
        },
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    invalidate()


def status_for(key: str) -> VerifyStatus:
    """The stored outcome for one connection, or untested.

    A row whose recorded envs no longer match what is set now reads untested:
    the credential changed under it, so the old answer is about a credential
    that is gone.
    """
    row = _load().get(key)
    if row is None:
        return UNTESTED
    if row.envs_present and _presence(row.envs_present) != row.envs_present:
        return UNTESTED
    return row


def all_statuses() -> dict[str, VerifyStatus]:
    """Every connection's current status, drift already applied."""
    return {key: status_for(key) for key in _load()}


def to_row(key: str) -> dict:
    """One status as the wire carries it: outcome, message, timestamp."""
    status = status_for(key)
    return {"outcome": status.outcome, "message": status.message, "checked_at": status.checked_at}


def record(key: str, ok: bool, message: str, envs) -> VerifyStatus:
    """Save the outcome of one probe, against the envs it resolved."""
    row = VerifyStatus(
        outcome=OUTCOME_OK if ok else OUTCOME_FAILED,
        message=message,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        envs_present=_presence(envs),
    )
    rows = dict(_load())
    rows[key] = row
    _write(rows)
    logger.info("connection status: %s recorded as %s", key, row.outcome)
    return row


def forget(key: str) -> None:
    """Drop one connection's stored outcome, if it has one."""
    rows = dict(_load())
    if rows.pop(key, None) is not None:
        _write(rows)
        logger.info("connection status: %s dropped", key)


def forget_for_env(env: str) -> None:
    """Drop every outcome that was checked against ``env``.

    Called on every settings write, so editing a token immediately stops its
    connection claiming the old verdict. The row names its own envs, which is
    why this needs no table of what depends on what.
    """
    rows = dict(_load())
    stale = [key for key, row in rows.items() if env in row.envs_present]
    if not stale:
        return
    for key in stale:
        rows.pop(key)
    _write(rows)
    logger.info("connection status: dropped %d row(s) after %s changed", len(stale), env)
