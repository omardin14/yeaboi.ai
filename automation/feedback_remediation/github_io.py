"""Thin ``gh`` CLI wrappers for the feedback-remediation pilot.

No PyGithub dependency — every call shells out to the ``gh`` CLI already
present on the GitHub Actions runner (and on the maintainer's machine for local
dry-runs), authenticated by ``GH_TOKEN``. All write operations honour a global
dry-run flag: when set, they log the intended action and change nothing.
"""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger("feedback_remediation")

_DRY_RUN = False


def set_dry_run(value: bool) -> None:
    """Toggle dry-run mode. When on, write calls only log their intent."""
    global _DRY_RUN
    _DRY_RUN = value


def _run(args: list[str]) -> str:
    """Run a ``gh`` command and return stdout (raises on non-zero exit)."""
    result = subprocess.run(  # noqa: S603 - args are code-controlled, never user input
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def list_open_issues(limit: int = 200) -> list[dict]:
    """Return open issues as dicts (number, title, body, author, labels, dates)."""
    out = _run(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,body,author,labels,createdAt,updatedAt",
        ]
    )
    return json.loads(out or "[]")


def add_labels(number: int, labels: list[str]) -> None:
    """Add labels to an issue (idempotent on GitHub's side)."""
    if not labels:
        return
    if _DRY_RUN:
        logger.info("[dry-run] would add labels %s to #%s", labels, number)
        return
    _run(["issue", "edit", str(number), "--add-label", ",".join(labels)])
    logger.info("added labels %s to #%s", labels, number)


def comment(number: int, body: str) -> None:
    """Post a comment on an issue."""
    if _DRY_RUN:
        logger.info("[dry-run] would comment on #%s: %s", number, body[:80])
        return
    _run(["issue", "comment", str(number), "--body", body])
    logger.info("commented on #%s", number)


def find_open_issue_by_label(label: str) -> int | None:
    """Return the number of the first open issue carrying ``label``, or None."""
    out = _run(["issue", "list", "--state", "open", "--label", label, "--json", "number"])
    rows = json.loads(out or "[]")
    return rows[0]["number"] if rows else None


def create_issue(title: str, body: str, labels: list[str]) -> int:
    """Create an issue and return its number."""
    if _DRY_RUN:
        logger.info("[dry-run] would create issue %r with labels %s", title, labels)
        return -1
    args = ["issue", "create", "--title", title, "--body", body]
    if labels:
        args += ["--label", ",".join(labels)]
    url = _run(args).strip()
    number = int(url.rstrip("/").rsplit("/", 1)[-1])
    logger.info("created issue #%s (%s)", number, title)
    return number


def update_issue_body(number: int, body: str) -> None:
    """Replace an issue's body (used to refresh the living digest/report issue)."""
    if _DRY_RUN:
        logger.info("[dry-run] would update body of #%s", number)
        return
    _run(["issue", "edit", str(number), "--body", body])
    logger.info("updated body of #%s", number)
