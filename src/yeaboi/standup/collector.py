"""Recent-activity collector for Daily Standup mode.

Fans out to every configured source (Jira, Azure DevOps, GitHub, local git,
Confluence), normalizes results into a single stream of activity items, and
tallies per-source counts. Every source is best-effort: an unconfigured or
failing source contributes zero items and never aborts the standup.

The per-source tool helpers are imported LAZILY inside each branch — their SDKs
(PyGithub, jira, azure-devops, atlassian) are optional extras that may not be
installed, exactly like tools/__init__.py:get_tools(). A missing SDK degrades
that one source to empty, same as a missing credential.

# See docs: "Daily Standup" — recent-activity collection
# See docs: "Tools" — lazy imports for optional integration SDKs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

logger = logging.getLogger(__name__)

# Canonical source identifiers (also used as the "source" tag on each item).
SOURCE_JIRA = "jira"
SOURCE_AZDO = "azure_devops"
SOURCE_AZDO_REPOS = "azdo_repos"  # AzDO git commits/PRs — separate key so a repo-API failure never hides work items
SOURCE_GITHUB = "github"
SOURCE_LOCAL_GIT = "local_git"
SOURCE_CONFLUENCE = "confluence"
SOURCE_NOTION = "notion"

ALL_SOURCES = (
    SOURCE_JIRA,
    SOURCE_AZDO,
    SOURCE_AZDO_REPOS,
    SOURCE_GITHUB,
    SOURCE_LOCAL_GIT,
    SOURCE_CONFLUENCE,
    SOURCE_NOTION,
)

# Human-readable reason shown when a source is auto-disabled (config missing).
_SKIP_REASONS = {
    SOURCE_JIRA: "JIRA_PROJECT_KEY not set",
    SOURCE_AZDO: "AZURE_DEVOPS_PROJECT not set",
    SOURCE_GITHUB: "STANDUP_GITHUB_REPO not set",
    SOURCE_LOCAL_GIT: "no repo path configured",
    SOURCE_CONFLUENCE: "CONFLUENCE_SPACE_KEY not set",
    SOURCE_NOTION: "NOTION_ROOT_PAGE_ID not set",
}


def previous_working_day_start(today: date) -> datetime:
    """Local midnight at the start of the last working day (Mon-Fri) before today.

    This is the standup activity-window start: a Monday (or weekend) run reaches
    back to Friday 00:00 so weekend standups still capture Friday's work, and a
    midweek run covers the FULL previous day plus today so far — not just the
    last 24 hours. Same Mon-Fri convention as confidence.working_days_between.
    """
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun → keep stepping back to Friday
        d -= timedelta(days=1)
    # tz-aware local midnight, so client-side helpers can compare against UTC.
    return datetime.combine(d, time.min).astimezone()


@dataclass
class ActivityBundle:
    """Normalized recent activity plus per-source counts and surfaced errors.

    items: each dict has {source, author, kind, title, timestamp, key}
        (+optional status, +optional author_email — best-effort, often hidden by
        Atlassian privacy settings, never rely on it being present).
    counts: (source, count) pairs for every source that was attempted.
    errors: (source, message) pairs for auth/other failures the user must see
        (e.g. a 401/403 that would otherwise look like "no activity").
    skipped: (source, reason) pairs for sources that were NOT attempted — missing
        config or SDK — so absent coverage is visible instead of silent.
    """

    items: list[dict] = field(default_factory=list)
    counts: list[tuple[str, int]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def total(self, *, exclude_kinds: tuple[str, ...] = ()) -> int:
        if not exclude_kinds:
            return len(self.items)
        return sum(1 for i in self.items if i.get("kind") not in exclude_kinds)

    def authors(self) -> list[str]:
        """Distinct non-empty author names seen across all activity, preserving order."""
        seen: dict[str, None] = {}
        for item in self.items:
            name = (item.get("author") or "").strip()
            if name and name not in seen:
                seen[name] = None
        return list(seen)


def _resolve_sources(
    explicit: set[str] | None,
    *,
    jira_project: str,
    azdo_project: str,
    github_repo: str,
    local_repo_path: str,
    confluence_space: str,
    notion_root: str = "",
) -> set[str]:
    """Decide which sources to attempt.

    When ``explicit`` is given, use it verbatim. Otherwise auto-enable a source
    when its identifying parameter is present (repo path, project key, etc.).
    """
    if explicit is not None:
        return set(explicit)
    auto: set[str] = set()
    if jira_project:
        auto.add(SOURCE_JIRA)
    if azdo_project:
        auto.add(SOURCE_AZDO)
        auto.add(SOURCE_AZDO_REPOS)  # same credential/project unlocks repo activity too
    if github_repo:
        auto.add(SOURCE_GITHUB)
    if local_repo_path:
        auto.add(SOURCE_LOCAL_GIT)
    if confluence_space:
        auto.add(SOURCE_CONFLUENCE)
    if notion_root:
        auto.add(SOURCE_NOTION)
    return auto


def collect_recent_activity(
    *,
    days: int = 1,
    since: datetime | None = None,
    sources: set[str] | None = None,
    jira_project: str = "",
    azdo_project: str = "",
    github_repo: str = "",
    local_repo_path: str = "",
    confluence_space: str = "",
    notion_root: str = "",
) -> ActivityBundle:
    """Gather and normalize recent activity from all enabled sources.

    The window is ``since → now``. Prefer passing ``since`` (the engine passes
    previous_working_day_start so weekend/Monday runs still cover Friday);
    ``days`` is the legacy now-minus-N-days fallback when ``since`` is None.

    Each source's helper already degrades to [] on error; this function adds the
    ``source`` tag, tallies counts, and guards the lazy import so a missing SDK
    (ImportError) simply skips that source.
    """
    enabled = _resolve_sources(
        sources,
        jira_project=jira_project,
        azdo_project=azdo_project,
        github_repo=github_repo,
        local_repo_path=local_repo_path,
        confluence_space=confluence_space,
        notion_root=notion_root,
    )
    logger.info(
        "collect_recent_activity: since=%s days=%d enabled sources=%s",
        since.isoformat() if since else None,
        days,
        sorted(enabled),
    )

    bundle = ActivityBundle()
    if sources is None:
        # Record WHY each source was auto-disabled so the report can show what
        # wasn't covered (a silently-skipped source reads as "no activity").
        for src in ALL_SOURCES:
            if src in enabled or src == SOURCE_AZDO_REPOS:
                continue  # azdo_repos shares azure_devops config — one skip line, not two
            bundle.skipped.append((src, _SKIP_REASONS.get(src, "not configured")))

    def _run(source: str, fetcher) -> None:
        """Call one source's fetcher, tag+append items, record the count."""
        from yeaboi.standup.errors import StandupSourceError

        try:
            raw = fetcher()
        except StandupSourceError as e:
            # Auth/other failure the user must see — record it as a warning.
            logger.warning("Source %s error surfaced: %s", source, e.message)
            bundle.errors.append((e.source, e.message))
            return
        except ImportError as e:
            logger.warning("Source %s skipped — SDK not installed: %s", source, e)
            bundle.skipped.append((source, "SDK not installed"))
            return
        except Exception as e:  # defensive — helpers already guard, but never let one source abort
            logger.warning("Source %s failed unexpectedly: %s", source, e)
            return
        for item in raw:
            item["source"] = source
            bundle.items.append(item)
        bundle.counts.append((source, len(raw)))
        logger.info("Source %s contributed %d item(s)", source, len(raw))

    if SOURCE_JIRA in enabled:

        def _jira() -> list[dict]:
            from yeaboi.tools.jira import jira_recent_activity

            return jira_recent_activity(jira_project, days=days, since=since)

        _run(SOURCE_JIRA, _jira)

    if SOURCE_AZDO in enabled:

        def _azdo() -> list[dict]:
            from yeaboi.tools.azure_devops import azdevops_recent_activity

            return azdevops_recent_activity(azdo_project, days=days, since=since)

        _run(SOURCE_AZDO, _azdo)

    if SOURCE_AZDO_REPOS in enabled:

        def _azdo_repos() -> list[dict]:
            from yeaboi.tools.azure_devops import azdevops_recent_commits, azdevops_recent_prs

            return azdevops_recent_commits(azdo_project, days=days, since=since) + azdevops_recent_prs(
                azdo_project, days=days, since=since
            )

        _run(SOURCE_AZDO_REPOS, _azdo_repos)

    if SOURCE_GITHUB in enabled:

        def _github() -> list[dict]:
            from yeaboi.tools.github import github_recent_commits, github_recent_prs

            return github_recent_commits(github_repo, days=days, since=since) + github_recent_prs(
                github_repo, days=days, since=since
            )

        _run(SOURCE_GITHUB, _github)

    if SOURCE_LOCAL_GIT in enabled:

        def _local() -> list[dict]:
            from yeaboi.tools.local_git import local_git_recent_commits

            return local_git_recent_commits(local_repo_path, days=days, since=since)

        _run(SOURCE_LOCAL_GIT, _local)

    if SOURCE_CONFLUENCE in enabled:

        def _conf() -> list[dict]:
            from yeaboi.tools.confluence import confluence_recent_pages

            return confluence_recent_pages(confluence_space, days=days, since=since)

        _run(SOURCE_CONFLUENCE, _conf)

    if SOURCE_NOTION in enabled:

        def _notion() -> list[dict]:
            from yeaboi.tools.notion import notion_recent_pages

            return notion_recent_pages(notion_root, days=days, since=since)

        _run(SOURCE_NOTION, _notion)

    _dedupe_items(bundle)
    logger.info("collect_recent_activity: %d total item(s) across %d source(s)", bundle.total(), len(bundle.counts))
    return bundle


def _dedupe_items(bundle: ActivityBundle) -> None:
    """Drop repeated items in place, keeping first occurrence.

    Identity is (source, kind, key, title-sans-annotation, lowercased author).
    Protects against the same commit arriving twice (e.g. once from the default
    branch scan and once via a PR's commit list — the sha key matches even though
    the PR variant's title carries a " (PR #N)" suffix) and a WIP ticket that
    also appeared in the changed-in-window query. Title stays part of the
    identity because local_git uses a constant key for every commit.
    """
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[dict] = []
    for item in bundle.items:
        key = str(item.get("key") or "")
        title = str(item.get("title") or "")
        kind = str(item.get("kind", ""))
        # A commit's sha key is discriminating on its own; drop the title so the
        # "(PR #N)"-annotated duplicate of a branch commit still collapses.
        # Every other kind keeps the title: ticket keys repeat across events
        # (two status moves of PROJ-1 are distinct items), and local_git uses a
        # constant "local" key for every commit.
        ident = (
            str(item.get("source", "")),
            kind,
            key,
            "" if (kind == "commit" and key and key != "local") else title,
            str(item.get("author", "")).strip().lower(),
        )
        if ident in seen:
            continue
        seen.add(ident)
        unique.append(item)
    if len(unique) != len(bundle.items):
        logger.info("collect_recent_activity: deduped %d repeated item(s)", len(bundle.items) - len(unique))
        bundle.items[:] = unique
