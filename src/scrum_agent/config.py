"""Configuration and environment variable handling."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


# ---------------------------------------------------------------------------
# User config directory (~/.scrum-agent/)
# ---------------------------------------------------------------------------


def get_config_dir() -> Path:
    """Return ~/.scrum-agent/, creating it if necessary."""
    d = Path.home() / ".scrum-agent"
    d.mkdir(exist_ok=True)
    return d


def get_config_file() -> Path:
    """Return path to ~/.scrum-agent/.env."""
    return get_config_dir() / ".env"


def get_sessions_db() -> Path:
    """Return path to ~/.scrum-agent/sessions.db (SQLite session store)."""
    return get_config_dir() / "sessions.db"


def load_user_config() -> None:
    """Load ~/.scrum-agent/.env without overriding existing env vars.

    Called once at CLI startup before any credential reads.
    dotenv's override=False means shell env vars and project .env always win
    — safe for CI/CD and developer overrides.
    """
    config_path = get_config_file()
    logger.info("Loading user config from %s", config_path)
    load_dotenv(config_path, override=False)
    logger.debug(
        "API keys — ANTHROPIC_API_KEY: %s, OPENAI_API_KEY: %s, GOOGLE_API_KEY: %s",
        "set" if os.getenv("ANTHROPIC_API_KEY") else "missing",
        "set" if os.getenv("OPENAI_API_KEY") else "missing",
        "set" if os.getenv("GOOGLE_API_KEY") else "missing",
    )
    logger.debug(
        "Integrations — GITHUB_TOKEN: %s, JIRA_API_TOKEN: %s, AZURE_DEVOPS_TOKEN: %s",
        "set" if os.getenv("GITHUB_TOKEN") else "missing",
        "set" if os.getenv("JIRA_API_TOKEN") else "missing",
        "set" if os.getenv("AZURE_DEVOPS_TOKEN") else "missing",
    )


def get_anthropic_api_key() -> str:
    """Return the Anthropic API key or raise if not set."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise OSError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
    return key


def is_langsmith_enabled() -> bool:
    """Check whether LangSmith tracing is enabled."""
    return os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def is_tips_enabled() -> bool:
    """Return True if on-screen discoverability tips should be shown (default on).

    Controls the rotating welcome-screen tip banner and the inline voice hints on
    text-entry screens. Any value other than "false" (case-insensitive) keeps tips
    on, so an unset var means enabled — the feature should be visible by default.
    """
    return os.getenv("TIPS_ENABLED", "true").strip().lower() != "false"


def set_tips_enabled(enabled: bool) -> None:
    """Persist the tips on/off preference to ~/.scrum-agent/.env and apply it now.

    Uses dotenv's set_key so only this one key is updated — save_config() rewrites
    the whole file and would drop any keys not passed to it. os.environ is updated
    too so the running session reflects the change immediately (no reload needed).
    """
    from dotenv import set_key

    value = "true" if enabled else "false"
    config_file = get_config_file()
    # set_key creates the file if missing and preserves existing keys/comments.
    set_key(str(config_file), "TIPS_ENABLED", value)
    os.environ["TIPS_ENABLED"] = value
    logger.info("Tips %s (persisted to %s)", "enabled" if enabled else "disabled", config_file)


def is_music_enabled() -> bool:
    """Return True if background music was left enabled (default off).

    Only records the on/off preference so the status bar can reflect it; playback
    itself is never auto-started (that would be surprise noise). Mirrors
    :func:`is_tips_enabled`.
    """
    return os.getenv("MUSIC_ENABLED", "false").strip().lower() == "true"


def set_music_enabled(enabled: bool) -> None:
    """Persist the music on/off preference to ~/.scrum-agent/.env and apply it now."""
    from dotenv import set_key

    value = "true" if enabled else "false"
    config_file = get_config_file()
    set_key(str(config_file), "MUSIC_ENABLED", value)
    os.environ["MUSIC_ENABLED"] = value
    logger.info("Music %s (persisted to %s)", "enabled" if enabled else "disabled", config_file)


def get_music_channel() -> int:
    """Return the persisted music channel index (defaults to 0)."""
    try:
        return int(os.getenv("MUSIC_CHANNEL", "0").strip())
    except ValueError:
        return 0


def set_music_channel(idx: int) -> None:
    """Persist the selected music channel index to ~/.scrum-agent/.env."""
    from dotenv import set_key

    value = str(int(idx))
    config_file = get_config_file()
    set_key(str(config_file), "MUSIC_CHANNEL", value)
    os.environ["MUSIC_CHANNEL"] = value
    logger.info("Music channel set to %s (persisted to %s)", value, config_file)


# Proxy environment variables to check (both uppercase and lowercase conventions).
_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def detect_proxy() -> str | None:
    """Return the first proxy URL found in environment variables, or None."""
    for var in _PROXY_ENV_VARS:
        value = os.getenv(var)
        if value:
            logger.debug("Proxy detected via %s", var)
            return value
    logger.debug("No proxy detected")
    return None


def get_github_token() -> str | None:
    """Return the GitHub PAT, or None if not set (tools work for public repos without a token)."""
    return os.getenv("GITHUB_TOKEN") or None


def get_azure_devops_token() -> str | None:
    """Return the Azure DevOps PAT, or None if not set."""
    return os.getenv("AZURE_DEVOPS_TOKEN") or None


def get_azure_devops_org_url() -> str | None:
    """Return the Azure DevOps organization URL (e.g. https://dev.azure.com/myorg), or None if not set."""
    return os.getenv("AZURE_DEVOPS_ORG_URL") or None


def get_azure_devops_project() -> str | None:
    """Return the Azure DevOps project name, or None if not set."""
    return os.getenv("AZURE_DEVOPS_PROJECT") or None


def get_azure_devops_team() -> str | None:
    """Return the Azure DevOps team name, or None if not set.

    Defaults to "{project} Team" when not explicitly set (AzDO's default team naming).
    """
    team = os.getenv("AZURE_DEVOPS_TEAM")
    if team:
        return team
    project = get_azure_devops_project()
    if project:
        return f"{project} Team"
    return None


def get_jira_base_url() -> str | None:
    """Return the Jira Cloud base URL (e.g. https://org.atlassian.net), or None if not set."""
    return os.getenv("JIRA_BASE_URL") or None


def get_jira_email() -> str | None:
    """Return the Atlassian account email used for Jira basic auth, or None if not set."""
    return os.getenv("JIRA_EMAIL") or None


def get_jira_token() -> str | None:
    """Return the Jira API token, or None if not set."""
    return os.getenv("JIRA_API_TOKEN") or None


def get_jira_project_key() -> str | None:
    """Return the default Jira project key (e.g. 'MYPROJ'), or None if not set."""
    return os.getenv("JIRA_PROJECT_KEY") or None


def get_confluence_space_key() -> str | None:
    """Return the default Confluence space key (e.g. 'MYSPACE'), or None if not set."""
    return os.getenv("CONFLUENCE_SPACE_KEY") or None


# ---------------------------------------------------------------------------
# Daily Standup configuration
# ---------------------------------------------------------------------------
# Non-secret standup settings (schedule time, channels) live in the SQLite
# standup_config table, keyed by session. Secrets and single-value integration
# creds live here in .env, same as the other integrations. get_standup_* getters
# read env; the two secret-bearing setters use dotenv.set_key like set_tips_enabled.


def get_standup_github_repo() -> str:
    """Return the GitHub repo (owner/repo or URL) to scan for standup code activity."""
    return os.getenv("STANDUP_GITHUB_REPO", "") or ""


def get_retro_server_port() -> int:
    """Return the base port for the Retro collaboration server (default 5173).

    The server walks upward from this port if it is busy (see retro/server.py).
    """
    try:
        return int(os.getenv("RETRO_PORT", "5173"))
    except ValueError:
        return 5173


def get_slack_webhook_url() -> str:
    """Return the Slack incoming-webhook URL for standup delivery, or '' if unset."""
    return os.getenv("SLACK_WEBHOOK_URL", "") or ""


def set_slack_webhook_url(url: str) -> None:
    """Persist the Slack webhook URL to ~/.scrum-agent/.env and apply it now."""
    from dotenv import set_key

    config_file = get_config_file()
    set_key(str(config_file), "SLACK_WEBHOOK_URL", url)
    os.environ["SLACK_WEBHOOK_URL"] = url
    logger.info("Slack webhook URL persisted to %s", config_file)


def get_smtp_host() -> str:
    """Return the SMTP host for standup email delivery, or '' if unset."""
    return os.getenv("STANDUP_SMTP_HOST", "") or ""


def get_smtp_port() -> int:
    """Return the SMTP port (default 587)."""
    try:
        return int(os.getenv("STANDUP_SMTP_PORT", "587") or "587")
    except ValueError:
        return 587


def get_smtp_user() -> str:
    """Return the SMTP username, or '' if unset."""
    return os.getenv("STANDUP_SMTP_USER", "") or ""


def get_smtp_password() -> str:
    """Return the SMTP password, or '' if unset."""
    return os.getenv("STANDUP_SMTP_PASSWORD", "") or ""


def set_smtp_password(password: str) -> None:
    """Persist the SMTP password to ~/.scrum-agent/.env and apply it now."""
    from dotenv import set_key

    config_file = get_config_file()
    set_key(str(config_file), "STANDUP_SMTP_PASSWORD", password)
    os.environ["STANDUP_SMTP_PASSWORD"] = password
    logger.info("SMTP password persisted to %s", config_file)


def get_smtp_sender() -> str:
    """Return the From address for standup emails (defaults to the SMTP user)."""
    return os.getenv("STANDUP_SMTP_SENDER", "") or get_smtp_user()


def get_standup_email_recipients() -> list[str]:
    """Return the standup email recipient list, parsed from a comma-separated env var."""
    raw = os.getenv("STANDUP_EMAIL_RECIPIENTS", "") or ""
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def get_standup_user_name() -> str:
    """Return the display name for the current user's self-reported standup update.

    Reads STANDUP_USER_NAME; defaults to "Me" so a solo user still gets a sensible
    label without configuration.
    """
    return os.getenv("STANDUP_USER_NAME", "").strip() or "Me"


# ---------------------------------------------------------------------------
# LLM provider configuration
# ---------------------------------------------------------------------------


def get_llm_provider() -> str:
    """Return the active LLM provider name (lowercase).

    Set LLM_PROVIDER in .env to switch providers. Defaults to 'anthropic'.
    Supported values: 'anthropic', 'openai', 'google'.
    """
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def get_llm_model() -> str | None:
    """Return the model ID override from LLM_MODEL env var, or None to use the provider default."""
    return os.getenv("LLM_MODEL") or None


def get_bedrock_region() -> str:
    """Return the AWS region for Bedrock API calls.

    Reads AWS_REGION, then AWS_DEFAULT_REGION from env. Defaults to 'us-east-1'.
    """
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def get_aws_profile() -> str | None:
    """Return the AWS profile to use for Bedrock API calls.

    Reads AWS_PROFILE from env. If not set, auto-detects from ~/.aws/config
    by finding the first profile with a region or role_arn configured.
    Returns None if only [default] is available (boto3 handles that automatically).
    """
    profile = os.getenv("AWS_PROFILE")
    if profile:
        return profile

    # Auto-detect: parse ~/.aws/config for non-default profiles
    try:
        config_path = Path.home() / ".aws" / "config"
        if config_path.exists():
            import configparser

            cfg = configparser.ConfigParser()
            cfg.read(config_path)
            for section in cfg.sections():
                # AWS config sections are [default] or [profile <name>]
                if section.startswith("profile "):
                    profile_name = section.removeprefix("profile ").strip()
                    if cfg.has_option(section, "role_arn") or cfg.has_option(section, "credential_source"):
                        return profile_name
    except Exception:
        pass

    return None


def get_openai_api_key() -> str | None:
    """Return the OpenAI API key, or None if not set."""
    return os.getenv("OPENAI_API_KEY") or None


def get_google_api_key() -> str | None:
    """Return the Google AI API key, or None if not set."""
    return os.getenv("GOOGLE_API_KEY") or None


def is_llm_configured() -> tuple[bool, str]:
    """Return (ok, message) for whether the selected LLM provider has credentials.

    Cheap, no network call — just checks the env var the active provider needs.
    Callers (e.g. the standup engine) use this to surface a clear "set your API
    key" message instead of silently degrading. Bedrock uses IAM, so a configured
    AWS region/profile counts as ready.
    """
    provider = get_llm_provider()
    if provider == "anthropic":
        return (bool(os.getenv("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY not set")
    if provider == "openai":
        return (bool(get_openai_api_key()), "OPENAI_API_KEY not set")
    if provider == "google":
        return (bool(get_google_api_key()), "GOOGLE_API_KEY not set")
    if provider == "bedrock":
        ok = bool(os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or get_aws_profile())
        return (ok, "AWS credentials/region not configured for Bedrock")
    return (bool(os.getenv("ANTHROPIC_API_KEY")), f"No API key configured for provider '{provider}'")


def get_voice_model() -> str:
    """Return the local Whisper model size for voice input.

    Transcription runs on-device via faster-whisper, so this is a model *size*,
    not a cloud model name. Override with the VOICE_MODEL env var. Valid values:
    ``tiny``, ``base`` (default), ``small``, ``medium``, ``large-v3`` (and the
    English-only ``.en`` variants). Larger = more accurate but slower and a
    bigger one-time download.
    """
    return os.getenv("VOICE_MODEL") or "base"


def get_session_prune_days() -> int:
    """Return the number of days after which old sessions are pruned.

    Phase 8C: reads ``SESSION_PRUNE_DAYS`` env var.
    Default is 30. Set to 0 to disable pruning. Invalid values fall back to 30.
    """
    raw = os.getenv("SESSION_PRUNE_DAYS", "30")
    try:
        value = int(raw)
        return value if value >= 0 else 30
    except ValueError:
        return 30


def get_log_level() -> str:
    """Return the configured log level for the file logger.

    Reads ``LOG_LEVEL`` from .env. Defaults to ``WARNING``.
    Valid values: DEBUG, INFO, WARNING, ERROR.
    Invalid values fall back to WARNING.
    """
    raw = os.getenv("LOG_LEVEL", "WARNING").upper()
    if raw in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return raw
    return "WARNING"


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_team_analysis_jira_dev_links_enabled() -> bool:
    """When true, team analysis calls Jira dev-status for linked PRs/repos (extra API calls)."""
    return _env_truthy("TEAM_ANALYSIS_JIRA_DEV_LINKS")


def is_team_analysis_azdo_pr_search_enabled() -> bool:
    """When true, team analysis scans AzDO Git PRs for work item links / branch names (extra API calls)."""
    return _env_truthy("TEAM_ANALYSIS_AZDO_BRANCH_SEARCH")


def get_team_analysis_azdo_pr_search_max_repos() -> int:
    """Max Git repos to scan per analysis when branch/PR search is enabled (1–50, default 10)."""
    raw = os.getenv("TEAM_ANALYSIS_AZDO_PR_SEARCH_MAX_REPOS", "10")
    try:
        return max(1, min(int(raw), 50))
    except ValueError:
        return 10


def get_team_analysis_azdo_pr_search_top() -> int:
    """Max pull requests per repo per status when PR search is enabled (10–200, default 75)."""
    raw = os.getenv("TEAM_ANALYSIS_AZDO_PR_SEARCH_PRS_PER_REPO", "75")
    try:
        return max(10, min(int(raw), 200))
    except ValueError:
        return 75


def get_team_analysis_azdo_repo_allowlist() -> frozenset[str] | None:
    """Optional comma-separated repo names (lowercase) to limit PR search; None = all repos up to max."""
    raw = os.getenv("TEAM_ANALYSIS_AZDO_REPO_ALLOWLIST", "").strip()
    if not raw:
        return None
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())


def disable_langsmith_tracing() -> None:
    """Disable LangSmith by unsetting LANGSMITH_TRACING in the current process.

    LangSmith reads LANGSMITH_TRACING from os.environ at runtime, so removing
    it prevents the SDK from attempting to send traces for the rest of the process.
    """
    logger.info("Disabling LangSmith tracing for this process")
    os.environ.pop("LANGSMITH_TRACING", None)
