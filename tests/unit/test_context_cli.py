"""Tests for the CLI's context flags (cli.py): what a run may read, and how it is labelled."""

from __future__ import annotations

import argparse
import io

import pytest

from yeaboi.cli import _cmd_standup, _context_kwargs, _context_spec, build_parser

SCOPED = ["report", "standup", "review run", "perf prep Ada", "perf review Ada", "analyze"]


def _parse(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


class TestFlags:
    @pytest.mark.parametrize("path", SCOPED)
    def test_every_run_subcommand_takes_the_three(self, path):
        args = _parse(
            [*path.split(), "--context", "standup@month", "--project-label", "Apollo", "--tag", "a", "--tag", "b"]
        )
        assert args.context.wants("standup") and not args.context.wants("retro")
        assert args.project_label == "Apollo" and args.tags == ["a", "b"]

    def test_perf_complete_takes_the_labels_only(self):
        args = _parse(["perf", "complete", "Ada", "--transcript", "notes", "--project-label", "Apollo"])
        # The flat planning --context lives on the root namespace; the subcommand adds none of its own.
        assert args.project_label == "Apollo" and args.context is None

    def test_the_flat_planning_flags(self):
        args = _parse(["--non-interactive", "--description", "x", "--context", "all", "--tag", "t"])
        assert args.context is not None and args.tags == ["t"]

    def test_a_typo_names_the_valid_sources(self, capsys):
        with pytest.raises(SystemExit):
            _parse(["standup", "--context", "stanup"])
        err = capsys.readouterr().err
        assert "stanup" in err and "standup" in err

    def test_none_is_incognito_and_inherit_is_nothing(self):
        assert _context_spec("none").incognito
        assert _context_spec("inherit") is None


class TestKwargs:
    def test_only_what_was_set_is_forwarded(self):
        assert _context_kwargs(argparse.Namespace(context=None, project_label="", tags=[])) == {}
        scope = _context_spec("standup@month")
        out = _context_kwargs(argparse.Namespace(context=scope, project_label="Apollo", tags=["a"]))
        assert out == {"context": scope, "project_label": "Apollo", "tags": ["a"]}

    def test_a_namespace_without_the_flags_forwards_nothing(self):
        assert _context_kwargs(argparse.Namespace()) == {}


class TestSetContext:
    def test_writes_the_saved_scope_and_does_not_run(self, monkeypatch, tmp_path):
        from rich.console import Console

        from yeaboi.standup.store import StandupStore

        db = tmp_path / "sessions.db"
        monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "sess-1")

        def never(*_a, **_k):
            raise AssertionError("--set-context must not run a standup")

        monkeypatch.setattr("yeaboi.standup.engine.run_standup", never)
        rc = _cmd_standup(_parse(["standup", "--set-context", "standup@month"]), Console(file=io.StringIO()))
        assert rc == 0
        with StandupStore(db) as store:
            assert store.get_context_scope("sess-1")["sources"] == ["standup"]

    def test_inherit_clears_it(self, monkeypatch, tmp_path):
        from rich.console import Console

        from yeaboi.context.scope import ContextScope
        from yeaboi.standup.store import StandupStore

        db = tmp_path / "sessions.db"
        monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "sess-1")
        with StandupStore(db) as store:
            store.set_context_scope("sess-1", ContextScope(sources=frozenset({"retro"})))
        assert _cmd_standup(_parse(["standup", "--set-context", "inherit"]), Console(file=io.StringIO())) == 0
        with StandupStore(db) as store:
            assert store.get_context_scope("sess-1") is None
