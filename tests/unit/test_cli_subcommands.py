"""Tests for the `yeaboi report/standup/perf/analyze` subcommands (cli.py).

The subcommand layer is additive — tests/integration/test_cli.py pins the flat
flags and stays untouched; this file covers the new headless mode runners.
"""

import argparse

import pytest

from yeaboi.agent.state import DeliveryReport, OneOnOnePrep, OneOnOneRecord, SixMonthReview, StandupReport
from yeaboi.cli import _cmd_analyze, _cmd_perf, _cmd_report, _cmd_standup, _run_subcommand, build_parser


def _console(buf=None):
    import io

    from rich.console import Console

    return Console(file=buf or io.StringIO(), width=100)


class TestParsing:
    def test_bare_invocation_has_no_command(self):
        args = build_parser().parse_args([])
        assert args.command is None

    def test_flat_flags_unaffected(self):
        args = build_parser().parse_args(["--standup-run", "--standup-session", "abc"])
        assert args.command is None
        assert args.standup_run is True
        assert args.standup_session == "abc"

    def test_report_parses(self):
        args = build_parser().parse_args(["report", "--period", "quarter", "--format", "json"])
        assert args.command == "report"
        assert args.period == "quarter"
        assert args.format == "json"

    def test_report_defaults(self):
        args = build_parser().parse_args(["report"])
        assert args.period == "last_sprint"
        assert args.session == ""
        assert args.format == "text"

    def test_standup_parses(self):
        args = build_parser().parse_args(["standup", "--deliver", "--channels", "slack", "email", "--days", "3"])
        assert args.command == "standup"
        assert args.deliver is True
        assert args.channels == ["slack", "email"]
        assert args.days == 3

    def test_standup_rejects_bad_channel(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["standup", "--channels", "pager"])

    def test_perf_requires_subcommand(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["perf"])

    def test_perf_prep_parses(self):
        args = build_parser().parse_args(["perf", "prep", "Sam"])
        assert args.command == "perf"
        assert args.perf_command == "prep"
        assert args.engineer == "Sam"

    def test_perf_complete_requires_transcript(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["perf", "complete", "Sam"])

    def test_analyze_parses(self):
        args = build_parser().parse_args(["analyze", "--source", "jira", "--sprints", "4", "--samples"])
        assert args.command == "analyze"
        assert args.source == "jira"
        assert args.sprints == 4
        assert args.samples is True
        assert args.no_insights is False


class TestReportCommand:
    def test_text_output(self, monkeypatch, capsys):
        captured: dict = {}

        def fake_report(period, *, session_id=""):
            captured.update(period=period, session_id=session_id)
            return DeliveryReport(period_label="Last sprint", executive_summary="Shipped.", warnings=("no tracker",))

        monkeypatch.setattr("yeaboi.reporting.engine.run_delivery_report", fake_report)
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "new-abc-2026-07-20")
        args = build_parser().parse_args(["report", "--period", "last_month"])
        assert _cmd_report(args, _console()) == 0
        assert captured == {"period": "last_month", "session_id": "new-abc-2026-07-20"}
        assert "no tracker" in capsys.readouterr().err

    def test_json_output_is_clean(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "yeaboi.reporting.engine.run_delivery_report",
            lambda period, *, session_id="": DeliveryReport(executive_summary="Shipped."),
        )
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "x")
        args = build_parser().parse_args(["report", "--format", "json"])
        assert _cmd_report(args, _console()) == 0
        import json

        payload = json.loads(capsys.readouterr().out)
        assert payload["executive_summary"] == "Shipped."


class TestStandupCommand:
    def test_no_session_exits_2(self, monkeypatch):
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: None)
        args = build_parser().parse_args(["standup"])
        assert _cmd_standup(args, _console()) == 2

    def test_runs_engine_with_overrides(self, monkeypatch):
        captured: dict = {}

        def fake_run(session_id, *, deliver, days, channels):
            captured.update(session_id=session_id, deliver=deliver, days=days, channels=channels)
            return StandupReport(team_summary="fine")

        monkeypatch.setattr("yeaboi.standup.engine.run_standup", fake_run)
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "sid")
        args = build_parser().parse_args(["standup", "--deliver", "--channels", "slack", "--days", "2"])
        assert _cmd_standup(args, _console()) == 0
        assert captured == {"session_id": "sid", "deliver": True, "days": 2, "channels": ["slack"]}


class TestPerfCommand:
    def test_roster_empty_exits_2(self, monkeypatch):
        monkeypatch.setattr("yeaboi.performance.roster.fetch_roster", lambda **kw: [])
        args = build_parser().parse_args(["perf", "roster"])
        assert _cmd_perf(args, _console()) == 2

    def test_prep(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.performance.engine.run_one_on_one_prep",
            lambda engineer, **kw: OneOnOnePrep(engineer=engineer),
        )
        args = build_parser().parse_args(["perf", "prep", "Sam"])
        assert _cmd_perf(args, _console()) == 0

    def test_complete_reads_transcript_file(self, monkeypatch, tmp_path):
        captured: dict = {}
        transcript_file = tmp_path / "notes.txt"
        transcript_file.write_text("we discussed growth\n")

        def fake_complete(engineer, transcript, *, deliver, **kw):
            captured.update(engineer=engineer, transcript=transcript, deliver=deliver)
            return OneOnOneRecord(engineer=engineer)

        monkeypatch.setattr("yeaboi.performance.engine.complete_one_on_one", fake_complete)
        args = build_parser().parse_args(["perf", "complete", "Sam", "--transcript", f"@{transcript_file}"])
        assert _cmd_perf(args, _console()) == 0
        assert captured == {"engineer": "Sam", "transcript": "we discussed growth", "deliver": False}

    def test_complete_missing_file_errors(self, tmp_path):
        args = build_parser().parse_args(["perf", "complete", "Sam", "--transcript", f"@{tmp_path}/nope.txt"])
        assert _cmd_perf(args, _console()) == 1

    def test_review_months_passthrough(self, monkeypatch):
        captured: dict = {}

        def fake_review(engineer, *, period_months, **kw):
            captured.update(engineer=engineer, period_months=period_months)
            return SixMonthReview(engineer=engineer)

        monkeypatch.setattr("yeaboi.performance.engine.run_six_month_review", fake_review)
        args = build_parser().parse_args(["perf", "review", "Sam", "--months", "12"])
        assert _cmd_perf(args, _console()) == 0
        assert captured == {"engineer": "Sam", "period_months": 12}

    def test_note_persists(self, monkeypatch, tmp_path):
        db = tmp_path / "sessions.db"
        monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
        args = build_parser().parse_args(["perf", "note", "Sam", "--text", "shipped the migration solo"])
        assert _cmd_perf(args, _console()) == 0

        from yeaboi.performance.store import PerformanceStore

        with PerformanceStore(db) as store:
            assert store.get_notes("Sam")[0]["note_text"] == "shipped the migration solo"


class TestAnalyzeCommand:
    def test_passthrough_and_summary(self, monkeypatch, capsys):
        from yeaboi.team_profile import TeamProfile

        captured: dict = {}

        def fake_analysis(**kwargs):
            captured.update(kwargs)
            return {
                "profile": TeamProfile(team_id="jira:P", source="jira", project_key="P"),
                "insights": {"start": [{"title": "Pairing"}], "stop": [], "keep": [], "try": []},
                "warnings": [],
            }

        monkeypatch.setattr("yeaboi.analysis.run_team_analysis", fake_analysis)
        args = build_parser().parse_args(["analyze", "--source", "jira", "--sprints", "4", "--no-insights"])
        assert _cmd_analyze(args, _console()) == 0
        assert captured["source"] == "jira"
        assert captured["sprint_count"] == 4
        assert captured["include_insights"] is False


class TestDispatch:
    def test_unhandled_error_returns_1(self, monkeypatch, capsys):
        def boom(period, **kw):
            raise ValueError("tracker exploded")

        monkeypatch.setattr("yeaboi.reporting.engine.run_delivery_report", boom)
        monkeypatch.setattr("yeaboi.cli._resolve_cli_session", lambda s: "x")
        args = build_parser().parse_args(["report"])
        assert _run_subcommand(args) == 1
        assert "tracker exploded" in capsys.readouterr().err

    def test_main_routes_commands(self, monkeypatch):
        from yeaboi import cli

        # Keep global state untouched: configure_logging() is idempotent (would
        # starve later logging tests) and load_user_config() would leak the real
        # ~/.yeaboi/.env credentials into os.environ for the rest of the run.
        monkeypatch.setattr("yeaboi.logging_setup.configure_logging", lambda: None)
        monkeypatch.setattr(cli, "load_user_config", lambda: None)
        monkeypatch.setattr(cli.paths, "migrate_root_dir", lambda: None)
        monkeypatch.setattr(cli, "_run_subcommand", lambda args: 0)
        with pytest.raises(SystemExit) as exc:
            cli.main(["report"])
        assert exc.value.code == 0

    def test_resolve_cli_session_prefers_explicit(self):
        from yeaboi.cli import _resolve_cli_session

        assert _resolve_cli_session("new-1234-2026-01-01") == "new-1234-2026-01-01"


def test_namespace_type_sanity():
    # The subparsers must not shadow existing flat-flag dests.
    args = build_parser().parse_args(["--quick"])
    assert isinstance(args, argparse.Namespace)
    assert args.quick is True
    assert args.command is None
