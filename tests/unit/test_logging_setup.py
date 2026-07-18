"""Tests for the central logging setup module (logging_setup.py)."""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from yeaboi import logging_setup
from yeaboi.logging_setup import (
    BACKUP_COUNT,
    DATE_FORMAT,
    LOG_FORMAT,
    MAX_BYTES,
    apply_level,
    attach_mode_handler,
    attach_session_log,
    configure_logging,
    detach,
    detach_session_log,
    mode_log,
)


@pytest.fixture(autouse=True)
def _isolated_logging(monkeypatch, tmp_path):
    """Point all log paths at tmp_path and guarantee no handler leaks."""
    monkeypatch.setattr("yeaboi.paths.LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr("yeaboi.paths.PLANNING_LOGS_DIR", tmp_path / "logs" / "planning")
    monkeypatch.setattr("yeaboi.paths.get_tui_log_path", lambda: tmp_path / "logs" / "tui" / "yeaboi.log")
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    yield
    for key in list(logging_setup._handlers):
        detach(key)


def _app_handlers():
    return [h for h in logging.getLogger("yeaboi").handlers if h in logging_setup._handlers.values()]


class TestConfigureLogging:
    def test_attaches_rotating_tui_handler(self, tmp_path):
        configure_logging()
        handler = logging_setup._handlers["tui"]
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == MAX_BYTES == 2 * 1024 * 1024
        assert handler.backupCount == BACKUP_COUNT == 3
        assert handler.formatter._fmt == LOG_FORMAT
        assert handler.formatter.datefmt == DATE_FORMAT
        assert handler.baseFilename.endswith("yeaboi.log")
        assert (tmp_path / "logs" / "tui").is_dir()

    def test_idempotent(self):
        configure_logging()
        configure_logging()
        assert len(_app_handlers()) == 1

    def test_default_level_is_warning(self):
        configure_logging()
        assert logging_setup._handlers["tui"].level == logging.WARNING

    def test_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        configure_logging()
        assert logging_setup._handlers["tui"].level == logging.DEBUG


class TestModeHandler:
    def test_creates_mode_log_file(self, tmp_path):
        attach_mode_handler("retro")
        handler = logging_setup._handlers["retro"]
        assert isinstance(handler, RotatingFileHandler)
        assert handler.baseFilename == str(tmp_path / "logs" / "retro" / "retro.log")

    def test_double_attach_is_noop(self):
        attach_mode_handler("standup")
        attach_mode_handler("standup")
        assert len(_app_handlers()) == 1

    def test_detach_removes_and_closes(self):
        attach_mode_handler("reporting")
        handler = logging_setup._handlers["reporting"]
        detach("reporting")
        assert "reporting" not in logging_setup._handlers
        assert handler not in logging.getLogger("yeaboi").handlers

    def test_detach_unknown_key_is_noop(self):
        detach("never-attached")  # must not raise

    def test_records_land_in_mode_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        attach_mode_handler("performance")
        logging.getLogger("yeaboi.test").info("hello from performance")
        detach("performance")
        content = (tmp_path / "logs" / "performance" / "performance.log").read_text()
        assert "hello from performance" in content
        assert "INFO" in content


class TestModeLogContextManager:
    def test_detaches_on_normal_exit(self):
        with mode_log("retro"):
            assert "retro" in logging_setup._handlers
        assert "retro" not in logging_setup._handlers

    def test_detaches_on_exception(self):
        with pytest.raises(RuntimeError), mode_log("retro"):
            raise RuntimeError("boom")
        assert "retro" not in logging_setup._handlers


class TestSessionLog:
    def test_creates_planning_session_file(self, tmp_path):
        attach_session_log("new-abc123-2026-07-18")
        handler = logging_setup._handlers["session"]
        assert isinstance(handler, RotatingFileHandler)
        assert handler.baseFilename == str(tmp_path / "logs" / "planning" / "new-abc123-2026-07-18.log")

    def test_new_session_replaces_previous(self):
        attach_session_log("session-one")
        first = logging_setup._handlers["session"]
        attach_session_log("session-two")
        second = logging_setup._handlers["session"]
        assert first is not second
        assert first not in logging.getLogger("yeaboi").handlers
        assert second.baseFilename.endswith("session-two.log")
        assert len(_app_handlers()) == 1

    def test_detach_session_log(self):
        attach_session_log("session-x")
        detach_session_log()
        assert "session" not in logging_setup._handlers


class TestApplyLevel:
    def test_updates_logger_and_all_handlers(self):
        configure_logging()
        attach_mode_handler("standup")
        apply_level("DEBUG")
        assert logging.getLogger("yeaboi").level == logging.DEBUG
        assert all(h.level == logging.DEBUG for h in logging_setup._handlers.values())
        apply_level("ERROR")
        assert logging.getLogger("yeaboi").level == logging.ERROR
        assert all(h.level == logging.ERROR for h in logging_setup._handlers.values())

    def test_invalid_level_falls_back_to_warning(self):
        configure_logging()
        apply_level("NOT-A-LEVEL")
        assert logging.getLogger("yeaboi").level == logging.WARNING

    def test_lowercase_accepted(self):
        configure_logging()
        apply_level("info")
        assert logging.getLogger("yeaboi").level == logging.INFO
