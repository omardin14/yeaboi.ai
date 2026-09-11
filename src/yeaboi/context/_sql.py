"""Two SQL fragments the history stores share for a scope's ``run_ids`` filter."""

from __future__ import annotations


def id_filter(run_ids: tuple[int, ...] | None, column: str = "id") -> tuple[str, tuple]:
    """``(clause, params)`` for a ``WHERE``: ``None`` matches every row, ``()`` none, else ``id IN (…)``."""
    if run_ids is None:
        return "1", ()
    if not run_ids:
        return "0", ()
    return f"{column} IN ({','.join('?' for _ in run_ids)})", tuple(int(i) for i in run_ids)


def limit_clause(limit: int) -> tuple[str, tuple]:
    """``LIMIT ?`` for a positive limit; nothing for ``0`` (every row)."""
    return (" LIMIT ?", (limit,)) if limit and limit > 0 else ("", ())
