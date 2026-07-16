"""Tests for configuration and environment variable handling."""

import os

import pytest

from yeaboi.config import (
    detect_proxy,
    disable_langsmith_tracing,
    get_anthropic_api_key,
    get_config_dir,
    get_config_file,
    get_session_prune_days,
    is_langsmith_enabled,
    is_tips_enabled,
    load_user_config,
    set_tips_enabled,
)


def test_get_anthropic_api_key_returns_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    assert get_anthropic_api_key() == "test-key-123"


def test_get_anthropic_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(OSError, match="ANTHROPIC_API_KEY is not set"):
        get_anthropic_api_key()


def test_langsmith_enabled_when_configured(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test-key")
    assert is_langsmith_enabled() is True


def test_langsmith_disabled_when_no_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert is_langsmith_enabled() is False


def test_langsmith_disabled_when_tracing_off(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test-key")
    assert is_langsmith_enabled() is False


def test_tips_enabled_by_default(monkeypatch):
    monkeypatch.delenv("TIPS_ENABLED", raising=False)
    assert is_tips_enabled() is True


def test_tips_enabled_true_value(monkeypatch):
    monkeypatch.setenv("TIPS_ENABLED", "true")
    assert is_tips_enabled() is True


def test_tips_disabled_when_false(monkeypatch):
    monkeypatch.setenv("TIPS_ENABLED", "false")
    assert is_tips_enabled() is False


def test_tips_disabled_case_insensitive(monkeypatch):
    monkeypatch.setenv("TIPS_ENABLED", "FALSE")
    assert is_tips_enabled() is False


def test_set_tips_enabled_round_trips(monkeypatch, tmp_path):
    # Point config at a temp file so we don't touch the real ~/.yeaboi/.env.
    config_file = tmp_path / ".env"
    monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)
    monkeypatch.delenv("TIPS_ENABLED", raising=False)

    set_tips_enabled(False)
    assert os.environ["TIPS_ENABLED"] == "false"
    assert "TIPS_ENABLED" in config_file.read_text()
    assert is_tips_enabled() is False

    set_tips_enabled(True)
    assert os.environ["TIPS_ENABLED"] == "true"
    assert is_tips_enabled() is True


def test_set_tips_enabled_preserves_other_keys(monkeypatch, tmp_path):
    config_file = tmp_path / ".env"
    config_file.write_text("ANTHROPIC_API_KEY=sk-existing\n")
    monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)

    set_tips_enabled(False)

    contents = config_file.read_text()
    assert "ANTHROPIC_API_KEY=sk-existing" in contents
    assert "TIPS_ENABLED" in contents


class TestProxyDetection:
    """Tests for proxy environment variable detection and LangSmith auto-disable."""

    def _clear_proxy_vars(self, monkeypatch):
        """Remove all proxy env vars so tests start from a clean state."""
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.delenv(var, raising=False)

    def test_detect_proxy_https(self, monkeypatch):
        self._clear_proxy_vars(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
        assert detect_proxy() == "http://proxy:8080"

    def test_detect_proxy_http(self, monkeypatch):
        self._clear_proxy_vars(monkeypatch)
        monkeypatch.setenv("HTTP_PROXY", "http://proxy:3128")
        assert detect_proxy() == "http://proxy:3128"

    def test_detect_proxy_lowercase(self, monkeypatch):
        self._clear_proxy_vars(monkeypatch)
        monkeypatch.setenv("https_proxy", "http://proxy:9090")
        assert detect_proxy() == "http://proxy:9090"

    def test_detect_proxy_none(self, monkeypatch):
        self._clear_proxy_vars(monkeypatch)
        assert detect_proxy() is None

    def test_disable_langsmith_tracing(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        disable_langsmith_tracing()
        assert "LANGSMITH_TRACING" not in os.environ


class TestGetConfigDir:
    """Tests for get_config_dir() — returns ~/.yeaboi/, creating it if absent."""

    def test_returns_yeaboi_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yeaboi.config.Path.home", lambda: tmp_path)
        result = get_config_dir()
        assert result == tmp_path / ".yeaboi"

    def test_creates_directory_if_absent(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yeaboi.config.Path.home", lambda: tmp_path)
        target = tmp_path / ".yeaboi"
        assert not target.exists()
        get_config_dir()
        assert target.is_dir()

    def test_no_error_if_directory_already_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yeaboi.config.Path.home", lambda: tmp_path)
        (tmp_path / ".yeaboi").mkdir()
        # Should not raise
        get_config_dir()


class TestGetConfigFile:
    """Tests for get_config_file() — returns ~/.yeaboi/.env path."""

    def test_returns_dot_env_inside_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yeaboi.config.Path.home", lambda: tmp_path)
        result = get_config_file()
        assert result == tmp_path / ".yeaboi" / ".env"


class TestLoadUserConfig:
    """Tests for load_user_config() — loads ~/.yeaboi/.env without overriding existing vars."""

    def test_loads_vars_from_file(self, monkeypatch, tmp_path):
        config_file = tmp_path / ".yeaboi" / ".env"
        config_file.parent.mkdir()
        config_file.write_text("TEST_LOAD_VAR=hello-from-file\n")
        monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)
        monkeypatch.delenv("TEST_LOAD_VAR", raising=False)
        load_user_config()
        assert os.environ.get("TEST_LOAD_VAR") == "hello-from-file"

    def test_does_not_override_existing_env_vars(self, monkeypatch, tmp_path):
        config_file = tmp_path / ".yeaboi" / ".env"
        config_file.parent.mkdir()
        config_file.write_text("TEST_OVERRIDE_VAR=from-file\n")
        monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)
        monkeypatch.setenv("TEST_OVERRIDE_VAR", "from-shell")
        load_user_config()
        # Shell value should win (override=False)
        assert os.environ.get("TEST_OVERRIDE_VAR") == "from-shell"

    def test_noop_when_file_absent(self, monkeypatch, tmp_path):
        config_file = tmp_path / ".yeaboi" / ".env"
        monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)
        # Should not raise even though the file doesn't exist
        load_user_config()


class TestGetSessionPruneDays:
    """Tests for get_session_prune_days() — SESSION_PRUNE_DAYS env var."""

    def test_default_30(self, monkeypatch):
        monkeypatch.delenv("SESSION_PRUNE_DAYS", raising=False)
        assert get_session_prune_days() == 30

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("SESSION_PRUNE_DAYS", "60")
        assert get_session_prune_days() == 60

    def test_zero_disables(self, monkeypatch):
        monkeypatch.setenv("SESSION_PRUNE_DAYS", "0")
        assert get_session_prune_days() == 0

    def test_negative_falls_back_to_30(self, monkeypatch):
        monkeypatch.setenv("SESSION_PRUNE_DAYS", "-5")
        assert get_session_prune_days() == 30

    def test_invalid_falls_back_to_30(self, monkeypatch):
        monkeypatch.setenv("SESSION_PRUNE_DAYS", "abc")
        assert get_session_prune_days() == 30


class TestStandupConfig:
    def test_github_repo(self, monkeypatch):
        from yeaboi.config import get_standup_github_repo

        monkeypatch.setenv("STANDUP_GITHUB_REPO", "owner/repo")
        assert get_standup_github_repo() == "owner/repo"

    def test_github_repo_default_empty(self, monkeypatch):
        from yeaboi.config import get_standup_github_repo

        monkeypatch.delenv("STANDUP_GITHUB_REPO", raising=False)
        assert get_standup_github_repo() == ""

    def test_slack_webhook(self, monkeypatch):
        from yeaboi.config import get_slack_webhook_url

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
        assert get_slack_webhook_url() == "https://hooks.slack.com/x"

    def test_smtp_port_default(self, monkeypatch):
        from yeaboi.config import get_smtp_port

        monkeypatch.delenv("STANDUP_SMTP_PORT", raising=False)
        assert get_smtp_port() == 587

    def test_smtp_port_invalid_falls_back(self, monkeypatch):
        from yeaboi.config import get_smtp_port

        monkeypatch.setenv("STANDUP_SMTP_PORT", "notaport")
        assert get_smtp_port() == 587

    def test_smtp_sender_defaults_to_user(self, monkeypatch):
        from yeaboi.config import get_smtp_sender

        monkeypatch.delenv("STANDUP_SMTP_SENDER", raising=False)
        monkeypatch.setenv("STANDUP_SMTP_USER", "me@example.com")
        assert get_smtp_sender() == "me@example.com"

    def test_email_recipients_parsed(self, monkeypatch):
        from yeaboi.config import get_standup_email_recipients

        monkeypatch.setenv("STANDUP_EMAIL_RECIPIENTS", "a@x.com, b@x.com ,")
        assert get_standup_email_recipients() == ["a@x.com", "b@x.com"]

    def test_email_recipients_empty(self, monkeypatch):
        from yeaboi.config import get_standup_email_recipients

        monkeypatch.delenv("STANDUP_EMAIL_RECIPIENTS", raising=False)
        assert get_standup_email_recipients() == []

    def test_set_slack_webhook_persists(self, monkeypatch, tmp_path):
        from yeaboi import config as cfg

        monkeypatch.setattr(cfg, "get_config_file", lambda: tmp_path / ".env")
        cfg.set_slack_webhook_url("https://hooks.slack.com/persisted")
        assert os.environ["SLACK_WEBHOOK_URL"] == "https://hooks.slack.com/persisted"
        assert "SLACK_WEBHOOK_URL" in (tmp_path / ".env").read_text()

    def test_user_name_default(self, monkeypatch):
        from yeaboi.config import get_standup_user_name

        monkeypatch.delenv("STANDUP_USER_NAME", raising=False)
        assert get_standup_user_name() == "Me"

    def test_user_name_from_env(self, monkeypatch):
        from yeaboi.config import get_standup_user_name

        monkeypatch.setenv("STANDUP_USER_NAME", "Omar")
        assert get_standup_user_name() == "Omar"

    def test_is_llm_configured_anthropic(self, monkeypatch):
        from yeaboi.config import is_llm_configured

        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
        assert is_llm_configured() == (True, "ANTHROPIC_API_KEY not set")

    def test_is_llm_configured_missing_key(self, monkeypatch):
        from yeaboi.config import is_llm_configured

        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ok, msg = is_llm_configured()
        assert ok is False
        assert "ANTHROPIC_API_KEY" in msg


class TestNotionConfig:
    """Notion has its own integration token (no shared Atlassian auth)."""

    def test_token_returns_value(self, monkeypatch):
        from yeaboi.config import get_notion_token

        monkeypatch.setenv("NOTION_TOKEN", "ntn_secret")
        assert get_notion_token() == "ntn_secret"

    def test_token_none_when_absent(self, monkeypatch):
        from yeaboi.config import get_notion_token

        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        assert get_notion_token() is None

    def test_root_page_id_returns_value(self, monkeypatch):
        from yeaboi.config import get_notion_root_page_id

        monkeypatch.setenv("NOTION_ROOT_PAGE_ID", "root123")
        assert get_notion_root_page_id() == "root123"

    def test_root_page_id_none_when_absent(self, monkeypatch):
        from yeaboi.config import get_notion_root_page_id

        monkeypatch.delenv("NOTION_ROOT_PAGE_ID", raising=False)
        assert get_notion_root_page_id() is None
