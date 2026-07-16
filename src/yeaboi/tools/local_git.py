"""Local git activity — a lightweight recent-commit reader for Daily Standup mode.

Unlike the other tool modules (github/jira/azdo) this needs no SDK or credentials:
it shells out to ``git log`` in a local working copy. Used by the standup collector
to round out the activity picture when the team's code lives in a local clone.

Plain functions (not @tool) — the standup collector calls them directly. They
degrade gracefully to [] on any error so a standup never crashes.

# See README: "Daily Standup" — recent-activity collection
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Unit-separator delimited format: author name, ISO date, subject.
# %x1f is the ASCII unit separator — safe against commit messages containing
# commas/pipes/tabs.
_LOG_FORMAT = "%an%x1f%aI%x1f%s"


def local_git_recent_commits(repo_path: str, days: int = 1) -> list[dict]:
    """Return commits in ``repo_path`` authored within the last ``days`` days.

    Each item: {author, kind='commit', title, timestamp, key(sha)}. Returns []
    when the path is not a git repo, git is unavailable, or the command fails.
    """
    logger.info("local_git_recent_commits: repo_path=%r days=%d", repo_path, days)
    if not repo_path:
        return []
    path = Path(repo_path).expanduser()
    if not path.is_dir():
        logger.warning("local_git_recent_commits skipped — not a directory: %s", path)
        return []
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "log",
                f"--since={int(days)} days ago",
                f"--pretty=format:{_LOG_FORMAT}",
                "--no-merges",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning("local_git_recent_commits failed to run git: %s", e)
        return []

    if proc.returncode != 0:
        # Non-zero: not a repo, bad path, etc. stderr is logged, not raised.
        logger.warning("local_git_recent_commits: git exited %d: %s", proc.returncode, proc.stderr.strip()[:200])
        return []

    items: list[dict] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        author, iso_date, subject = parts
        items.append(
            {
                "author": author,
                "kind": "commit",
                "title": subject,
                "timestamp": iso_date[:19],
                "key": "local",
            }
        )
    logger.info("local_git_recent_commits: %d commit(s) in last %d day(s)", len(items), days)
    return items
