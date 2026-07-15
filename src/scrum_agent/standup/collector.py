"""Recent-activity collector for Daily Standup mode.

Fans out to every configured source (Jira, Azure DevOps, GitHub, local git,
Confluence), normalizes results into a single stream of activity items, and
tallies per-source counts. Every source is best-effort: an unconfigured or
failing source contributes zero items and never aborts the standup.

The per-source tool helpers are imported LAZILY inside each branch — their SDKs
(PyGithub, jira, azure-devops, atlassian) are optional extras that may not be
installed, exactly like tools/__init__.py:get_tools(). A missing SDK degrades
that one source to empty, same as a missing credential.

# See README: "Daily Standup" — recent-activity collection
# See README: "Tools" — lazy imports for optional integration SDKs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Canonical source identifiers (also used as the "source" tag on each item).
SOURCE_JIRA = "jira"
SOURCE_AZDO = "azure_devops"
SOURCE_GITHUB = "github"
SOURCE_LOCAL_GIT = "local_git"
SOURCE_CONFLUENCE = "confluence"
SOURCE_NOTION = "notion"

ALL_SOURCES = (SOURCE_JIRA, SOURCE_AZDO, SOURCE_GITHUB, SOURCE_LOCAL_GIT, SOURCE_CONFLUENCE, SOURCE_NOTION)


@dataclass
class ActivityBundle:
    """Normalized recent activity plus per-source counts and surfaced errors.

    items: each dict has {source, author, kind, title, timestamp, key} (+optional status).
    counts: (source, count) pairs for every source that was attempted.
    errors: (source, message) pairs for auth/other failures the user must see
        (e.g. a 401/403 that would otherwise look like "no activity").
    """

    items: list[dict] = field(default_factory=list)
    counts: list[tuple[str, int]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def total(self) -> int:
        return len(self.items)

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
    sources: set[str] | None = None,
    jira_project: str = "",
    azdo_project: str = "",
    github_repo: str = "",
    local_repo_path: str = "",
    confluence_space: str = "",
    notion_root: str = "",
) -> ActivityBundle:
    """Gather and normalize recent activity from all enabled sources.

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
    logger.info("collect_recent_activity: days=%d enabled sources=%s", days, sorted(enabled))

    bundle = ActivityBundle()

    def _run(source: str, fetcher) -> None:
        """Call one source's fetcher, tag+append items, record the count."""
        from scrum_agent.standup.errors import StandupSourceError

        try:
            raw = fetcher()
        except StandupSourceError as e:
            # Auth/other failure the user must see — record it as a warning.
            logger.warning("Source %s error surfaced: %s", source, e.message)
            bundle.errors.append((e.source, e.message))
            return
        except ImportError as e:
            logger.warning("Source %s skipped — SDK not installed: %s", source, e)
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
            from scrum_agent.tools.jira import jira_recent_activity

            return jira_recent_activity(jira_project, days=days)

        _run(SOURCE_JIRA, _jira)

    if SOURCE_AZDO in enabled:

        def _azdo() -> list[dict]:
            from scrum_agent.tools.azure_devops import azdevops_recent_activity

            return azdevops_recent_activity(azdo_project, days=days)

        _run(SOURCE_AZDO, _azdo)

    if SOURCE_GITHUB in enabled:

        def _github() -> list[dict]:
            from scrum_agent.tools.github import github_recent_commits, github_recent_prs

            return github_recent_commits(github_repo, days=days) + github_recent_prs(github_repo, days=days)

        _run(SOURCE_GITHUB, _github)

    if SOURCE_LOCAL_GIT in enabled:

        def _local() -> list[dict]:
            from scrum_agent.tools.local_git import local_git_recent_commits

            return local_git_recent_commits(local_repo_path, days=days)

        _run(SOURCE_LOCAL_GIT, _local)

    if SOURCE_CONFLUENCE in enabled:

        def _conf() -> list[dict]:
            from scrum_agent.tools.confluence import confluence_recent_pages

            return confluence_recent_pages(confluence_space, days=days)

        _run(SOURCE_CONFLUENCE, _conf)

    if SOURCE_NOTION in enabled:

        def _notion() -> list[dict]:
            from scrum_agent.tools.notion import notion_recent_pages

            return notion_recent_pages(notion_root, days=days)

        _run(SOURCE_NOTION, _notion)

    logger.info("collect_recent_activity: %d total item(s) across %d source(s)", bundle.total(), len(bundle.counts))
    return bundle
