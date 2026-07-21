"""Plaintext serializer for the Usage dashboard — the "Copy to clipboard" content.

The Usage page has no on-disk export; this turns the ``_collect_usage_data()`` dict
(ui/mode_select/__init__.py) into a readable ``label: value`` report the user can
copy out of the terminal and paste into an issue, a message, or notes. Pure and
defensive — every field is optional, so a partial dict still renders.
"""

from __future__ import annotations


def _money(v) -> str:
    try:
        return f"${float(v):.4f}"
    except (TypeError, ValueError):
        return str(v)


def _tokens_block(title: str, t: dict) -> list[str]:
    if not t:
        return [f"{title}: (none)"]
    return [
        f"{title}:",
        f"  Calls:           {t.get('calls', 0)}",
        f"  Input tokens:    {t.get('input', 0):,}",
        f"  Output tokens:   {t.get('output', 0):,}",
        f"  Total tokens:    {t.get('total', 0):,}",
        f"  Estimated cost:  {_money(t.get('estimated_cost', 0))}",
    ]


def build_usage_text(data: dict) -> str:
    """Render the Usage dashboard data as a copy-pasteable plaintext report."""
    data = data or {}
    lines: list[str] = ["yeaboi — Usage summary", "=" * 24, ""]

    lines.append("Provider")
    lines.append(f"  LLM provider:    {data.get('provider', '?')}")
    lines.append(f"  Model:           {data.get('model', '?')}")
    lines.append(f"  API key:         {data.get('api_key_status', '?')}")
    lines.append("")

    sess = data.get("sessions") or {}
    lines.append("Sessions")
    lines.append(f"  Total:           {sess.get('total', 0)}")
    lines.append(f"  Planning:        {sess.get('planning', 0)}")
    lines.append(f"  Analysis:        {sess.get('analysis', 0)}")
    if sess.get("last_used"):
        lines.append(f"  Last used:       {sess['last_used']}")
    lines.append("")

    lines.extend(_tokens_block("This session", data.get("tokens") or {}))
    lines.append("")
    lines.extend(_tokens_block("Lifetime", data.get("lifetime_tokens") or {}))
    lines.append("")

    perf = data.get("local_performance") or {}
    if perf:
        lines.append("Local model performance")
        for k, v in perf.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    profiles = data.get("profiles") or []
    if profiles:
        lines.append("Team profiles")
        for p in profiles:
            lines.append(f"  - {p.get('name', '?')} ({p.get('source', '?')}, {p.get('sprints', 0)} sprints)")
        lines.append("")

    lines.append("Environment")
    lines.append(f"  yeaboi version:  {data.get('version', '?')}")
    lines.append(f"  Python:          {data.get('python_version', '?')}")
    lines.append(f"  LangSmith:       {data.get('langsmith', '?')}")
    lines.append(f"  Database:        {data.get('db_path', '?')}")

    return "\n".join(lines).rstrip() + "\n"
