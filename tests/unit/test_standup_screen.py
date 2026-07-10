"""Render tests for the Daily Standup TUI screen builder and helpers."""

from rich.panel import Panel

from scrum_agent.agent.state import MemberUpdate, StandupReport
from scrum_agent.ui.mode_select.screens._screens import _MODE_CARDS
from scrum_agent.ui.mode_select.screens._screens_secondary import _build_standup_screen
from scrum_agent.ui.shared._components import STANDUP_THEME, standup_title


def _report() -> StandupReport:
    return StandupReport(
        date="2026-07-10",
        sprint_name="Sprint 5",
        sprint_day=3,
        sprint_total_days=10,
        confidence_pct=82,
        confidence_label="At risk",
        confidence_rationale="behind ideal burn",
        team_summary="steady progress",
        member_updates=(
            MemberUpdate(name="Alice", summary="login page", source="inferred"),
            MemberUpdate(name="Bob", summary="paired on auth", blockers="waiting on review", source="self-reported"),
        ),
        activity_counts=(("github", 2), ("jira", 1)),
    )


class TestComponents:
    def test_theme_is_magenta(self):
        assert STANDUP_THEME.accent == "rgb(200,100,180)"

    def test_title_returns_text(self):
        from rich.text import Text

        assert isinstance(standup_title(), Text)

    def test_mode_card_registered(self):
        keys = {c["key"] for c in _MODE_CARDS}
        assert "daily-standup" in keys

    def test_color_registered(self):
        from scrum_agent.ui.shared._animations import COLOR_RGB

        assert COLOR_RGB["rgb(200,100,180)"] == (200, 100, 180)


class TestBuildStandupScreen:
    def test_returns_panel_with_report(self):
        data = {
            "session_name": "demo-2026-07-10",
            "config": {"enabled": True, "time": "09:50", "weekdays": "1-5", "delivery_channels": ["terminal"]},
            "schedule": {"installed": True, "platform": "launchd"},
            "report": _report(),
            "message": "",
        }
        panel = _build_standup_screen(data, width=100, height=30)
        assert isinstance(panel, Panel)

    def test_handles_empty_data(self):
        panel = _build_standup_screen({}, width=80, height=24)
        assert isinstance(panel, Panel)

    def test_handles_no_report_no_config(self):
        data = {"session_name": "demo", "config": None, "schedule": {}, "report": None, "message": "hi"}
        panel = _build_standup_screen(data, width=80, height=24)
        assert isinstance(panel, Panel)

    def test_scrollable_at_small_height(self):
        # A tall report in a short viewport must still build (scrollbar path).
        data = {"session_name": "demo", "report": _report(), "schedule": {"installed": False}}
        panel = _build_standup_screen(data, width=60, height=12, scroll_offset=5)
        assert isinstance(panel, Panel)

    def test_action_selection_variants(self):
        data = {"report": _report(), "schedule": {}}
        for sel in range(5):  # Generate, My Update, Configure, Export, Back
            assert isinstance(_build_standup_screen(data, width=80, height=24, action_sel=sel), Panel)

    def test_report_renders_as_themed_rows_not_emoji(self):
        # The dashboard should use clean label/value rows, not the plaintext
        # emoji dump used for Slack/email delivery.
        from rich.console import Console

        panel = _build_standup_screen({"report": _report(), "schedule": {"installed": False}}, width=100, height=60)
        console = Console(width=110, file=open("/dev/null", "w"))
        with console.capture() as cap:
            console.print(panel)
        out = cap.get()
        assert "Confidence:" in out
        assert "At risk" in out
        assert "🟡" not in out and "🟢" not in out  # no emoji in the TUI dashboard

    def test_warnings_render_as_notices(self):
        from rich.console import Console

        rep = StandupReport(
            date="2026-07-10",
            warnings=(
                "Jira: authentication failed — check token",
                "AI summary unavailable — ANTHROPIC_API_KEY not set",
            ),
        )
        panel = _build_standup_screen({"report": rep, "schedule": {"installed": False}}, width=100, height=60)
        console = Console(width=110, file=open("/dev/null", "w"))
        with console.capture() as cap:
            console.print(panel)
        out = cap.get()
        assert "Notices" in out
        assert "authentication failed" in out
        assert "ANTHROPIC_API_KEY not set" in out

    def test_schedule_shows_standup_time_and_runs_at(self):
        from rich.console import Console

        data = {
            "config": {
                "enabled": True,
                "time": "10:00",
                "lead_minutes": 10,
                "weekdays": "1-5",
                "delivery_channels": ["terminal"],
            },
            "schedule": {"installed": True, "platform": "launchd"},
            "report": None,
        }
        panel = _build_standup_screen(data, width=100, height=60)
        console = Console(width=110, file=open("/dev/null", "w"))
        with console.capture() as cap:
            console.print(panel)
        out = cap.get()
        assert "Standup time:" in out and "10:00" in out
        assert "Runs at:" in out and "09:50" in out


class TestBuildStandupInputScreen:
    def test_returns_panel(self):
        from scrum_agent.ui.mode_select.screens._screens_secondary import _build_standup_input_screen

        panel = _build_standup_input_screen(
            "Standup time (HH:MM)", "09:5", step="Configure standup  (1/5)", default="09:50", width=80, height=24
        )
        assert isinstance(panel, Panel)

    def test_shows_prompt_value_and_hint(self):
        from rich.console import Console

        from scrum_agent.ui.mode_select.screens._screens_secondary import _build_standup_input_screen

        panel = _build_standup_input_screen("Your name", "Ali", step="My update  (1/2)", width=90, height=24)
        console = Console(width=100, file=open("/dev/null", "w"))
        with console.capture() as cap:
            console.print(panel)
        out = cap.get()
        assert "Your name" in out
        assert "Ali" in out
        assert "Esc to cancel" in out


class TestSettingsMasksStandupSecrets:
    def test_slack_and_smtp_password_masked(self):
        from scrum_agent.ui.mode_select.screens._screens_secondary import _build_settings_screen

        data = {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/SECRET123456",
            "STANDUP_SMTP_PASSWORD": "supersecretpw",
            "STANDUP_SMTP_HOST": "smtp.example.com",
            "_config_path": "/tmp/.env",
        }
        panel = _build_settings_screen(data, width=100, height=90)
        # Render to text and confirm the raw secret does not appear.
        from rich.console import Console

        console = Console(width=120, file=open("/dev/null", "w"))
        with console.capture() as cap:
            console.print(panel)
        out = cap.get()
        assert "SECRET123456" not in out
        assert "supersecretpw" not in out
        assert "smtp.example.com" in out  # non-secret shown
