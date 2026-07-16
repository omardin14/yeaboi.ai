"""Tests for the LLM model-selection step of the provider setup wizard.

Covers:
- ``_verify_model`` live-validation per provider (happy + error paths, mocked).
- The two new screen builders (render, plaintext-not-masked, states).
- Data integrity: each card's default model matches ``_PROVIDER_DEFAULTS``.
- ``run_setup_wizard`` propagates the chosen model to ``LLM_MODEL``.
"""

from io import StringIO

import pytest
from rich.console import Console
from rich.panel import Panel

from yeaboi.agent.llm import _PROVIDER_DEFAULTS
from yeaboi.setup_wizard import _PROVIDERS, run_setup_wizard
from yeaboi.ui.provider_select._constants import (
    _AZDEVOPS_TRACKING_FIELDS,
    _CONFLUENCE_FIELDS,
    _ISSUE_TRACKING_FIELDS,
    _NOTION_FIELDS,
    _PROVIDER_CARDS,
)
from yeaboi.ui.provider_select._nav import (
    _LAST_STEP,
    _STEP_LLM,
    StepNav,
    nav_for_key,
)
from yeaboi.ui.provider_select._verification import (
    _verify_confluence,
    _verify_model,
    fetch_available_models,
)
from yeaboi.ui.provider_select.screens._screens import (
    _STEPS,
    _build_model_input_screen,
    _build_model_loading_screen,
    _build_model_select_screen,
    _build_progress,
    _build_screen_frame,
)
from yeaboi.ui.provider_select.screens._screens_vc import _build_hint_text, _build_issue_tracking_screen
from yeaboi.ui.shared._wordmarks import get_shadow_wordmark

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _card(provider_val: str) -> dict:
    return next(c for c in _PROVIDER_CARDS if c["provider_val"] == provider_val)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _render(panel: Panel) -> str:
    console = Console(file=StringIO(), width=80, highlight=False)
    console.print(panel)
    return console.file.getvalue()


def _console() -> Console:
    return Console(file=StringIO(), width=80)


class _FakeLive:
    """Collects the renderables passed to live.update() (no real terminal)."""

    def __init__(self):
        self.frames = []

    def update(self, renderable):
        self.frames.append(renderable)


class _KeySequence:
    def __init__(self, keys):
        self._keys = list(keys)

    def __call__(self, timeout=None):
        return self._keys.pop(0) if self._keys else ""


# ---------------------------------------------------------------------------
# _verify_model — Anthropic
# ---------------------------------------------------------------------------


class TestVerifyModelAnthropic:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("anthropic"), "sk-ant-key", "claude-opus-4-8")
        assert ok is True

    def test_unknown_model_404(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-nope")
        assert ok is False
        assert "not" in msg.lower()

    def test_bad_request_surfaces_detail(self, monkeypatch):
        import httpx

        payload = {"error": {"message": "model: claude-nope is not supported"}}
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(400, payload))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-nope")
        assert ok is False
        assert "not supported" in msg

    def test_bad_credentials_401(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(401))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-bad", "claude-opus-4-8")
        assert ok is False
        assert "Invalid" in msg

    def test_connection_error(self, monkeypatch):
        import httpx

        def _boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(httpx, "post", _boom)
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-opus-4-8")
        assert ok is False
        assert "Connection error" in msg


# ---------------------------------------------------------------------------
# _verify_model — OpenAI / Google
# ---------------------------------------------------------------------------


class TestVerifyModelOpenAI:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("openai"), "sk-key", "gpt-4o")
        assert ok is True

    def test_unknown_model(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("openai"), "sk-key", "gpt-nope")
        assert ok is False
        assert "Unknown" in msg


class TestVerifyModelGoogle:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("google"), "AIzaKey", "gemini-2.5-flash")
        assert ok is True

    def test_unknown_model(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("google"), "AIzaKey", "gemini-nope")
        assert ok is False
        assert "Unknown" in msg


# ---------------------------------------------------------------------------
# _verify_model — Bedrock (api_key is the region)
# ---------------------------------------------------------------------------


class TestVerifyModelBedrock:
    def test_inference_profile_soft_accepted_without_api_call(self):
        # Leading us./eu./global. ids aren't in list_foundation_models — accept
        # once the region resolves. No boto3 needed, so no mock required.
        ok, _ = _verify_model(_card("bedrock"), "us-east-1", "us.anthropic.claude-sonnet-4-20250514-v1:0")
        assert ok is True

    def _inject_boto3(self, monkeypatch, model_summaries):
        """Inject a fake boto3 module (the real one is an optional extra)."""
        import sys
        import types

        class _Client:
            def list_foundation_models(self, **kw):
                return {"modelSummaries": model_summaries}

        class _Session:
            def __init__(self, *a, **kw):
                pass

            def client(self, *a, **kw):
                return _Client()

        fake = types.ModuleType("boto3")
        fake.Session = _Session
        monkeypatch.setitem(sys.modules, "boto3", fake)
        monkeypatch.setattr("yeaboi.config.get_aws_profile", lambda: None)

    def test_plain_model_id_found_in_region(self, monkeypatch):
        self._inject_boto3(monkeypatch, [{"modelId": "anthropic.claude-3-sonnet"}])
        ok, _ = _verify_model(_card("bedrock"), "us-east-1", "anthropic.claude-3-sonnet")
        assert ok is True

    def test_plain_model_id_missing_in_region(self, monkeypatch):
        self._inject_boto3(monkeypatch, [])
        ok, msg = _verify_model(_card("bedrock"), "us-east-1", "anthropic.claude-3-sonnet")
        assert ok is False
        assert "not available" in msg.lower()


class TestVerifyModelUnknownProvider:
    def test_unknown_provider_returns_false(self):
        ok, msg = _verify_model({"provider_val": "mystery"}, "key", "some-model")
        assert ok is False
        assert "Unknown provider" in msg


# ---------------------------------------------------------------------------
# Screen builders
# ---------------------------------------------------------------------------


class TestModelSelectScreen:
    def test_returns_panel(self):
        panel = _build_model_select_screen(_card("anthropic"), ["claude-opus-4-8", "Custom…"], 0)
        assert isinstance(panel, Panel)

    def test_single_entry(self):
        panel = _build_model_select_screen(_card("openai"), ["Custom…"], 0)
        assert isinstance(panel, Panel)

    def test_long_model_id_renders(self):
        entries = ["us.anthropic.claude-sonnet-4-20250514-v1:0", "Custom…"]
        out = _render(_build_model_select_screen(_card("bedrock"), entries, 0))
        # The id is long enough it may wrap/crop; a distinctive fragment survives.
        assert "claude-sonnet-4" in out

    def test_error_line_shown(self):
        out = _render(_build_model_select_screen(_card("openai"), ["gpt-4o", "Custom…"], 0, error="Unknown model"))
        assert "Unknown model" in out

    def test_renders_as_rounded_cards(self):
        # Each model is a rounded box-drawing card (matches app cards/buttons),
        # not plain text — the corner glyphs must be present.
        out = _render(_build_model_select_screen(_card("anthropic"), ["claude-opus-4-8", "Custom…"], 0))
        assert "╭" in out and "╰" in out
        assert "claude-opus-4-8" in out

    def test_long_list_windows_with_more_hint(self):
        # More models than fit a short screen → window + a "N more" affordance,
        # and the render must not exceed the frame height.
        entries = [f"model-{i}" for i in range(12)] + ["Custom…"]
        panel = _build_model_select_screen(_card("openai"), entries, 6, width=80, height=24)
        out = _render(panel)
        assert "more" in out
        assert out.count("\n") <= 24


class TestModelInputScreen:
    def test_returns_panel(self):
        assert isinstance(_build_model_input_screen(_card("anthropic"), ""), Panel)

    def test_value_is_plaintext_not_masked(self):
        # Model ids are not secrets — the typed value must render as-is, no bullets.
        out = _render(_build_model_input_screen(_card("anthropic"), "claude-opus-4-8"))
        assert "claude-opus-4-8" in out
        assert "•" not in out

    def test_verified_state(self):
        assert isinstance(_build_model_input_screen(_card("openai"), "gpt-4o", verified=True), Panel)

    def test_error_state(self):
        out = _render(_build_model_input_screen(_card("openai"), "gpt-nope", verified=False, error="Unknown model"))
        assert "Unknown model" in out

    def test_verifying_state(self):
        panel = _build_model_input_screen(
            _card("google"), "gemini-2.5-flash", verifying=True, border_override="rgb(1,1,1)"
        )
        assert isinstance(panel, Panel)


class TestModelLoadingScreen:
    def test_returns_panel_with_discovery_text(self):
        # Shown (animated) while live discovery runs on a background thread so the
        # Live loop never freezes on a blocking HTTP call.
        out = _render(_build_model_loading_screen(_card("anthropic"), 0.3, width=80, height=24))
        assert "Discovering available models" in out

    def test_title_is_provider_name(self):
        # The per-screen title carries the provider identity (tall ANSI-Shadow).
        out = _render(_build_model_loading_screen(_card("anthropic"), 0.0))
        assert "█" in out


class TestFrameTitleFont:
    """The frame title renders in the tall ANSI-Shadow font, with a compact fallback."""

    def _frame(self, title, width):
        from rich.text import Text

        return _build_screen_frame(
            subtitle="x",
            step=0,
            body_items=[Text("body")],
            body_height=1,
            width=width,
            height=30,
            title_text=title,
        )

    def test_tall_wordmark_at_wide_width(self):
        # A baked word (provider name) renders as the tall blocky wordmark.
        out = _render(self._frame("Anthropic", 100))
        assert "█" in out

    def test_compact_fallback_at_narrow_width(self):
        # Too narrow for the ~70-col wordmark → falls back to the compact 2-line
        # block font (still block chars, but the wide wordmark row can't fit).
        panel = self._frame("Anthropic", 40)
        console = Console(file=StringIO(), width=40, highlight=False)
        console.print(panel)
        out = console.file.getvalue()
        # Compact font uses ▀/▄ half-blocks the tall wordmark never emits.
        assert "▀" in out or "▄" in out

    def test_default_title_is_setup_not_setup_wizard(self):
        out = _render(self._frame("", 100))
        # "SETUP" wordmark present; the old "Setup Wizard" compact string is gone.
        assert "█" in out


class TestIssueTrackingHint:
    """The multi-field form (Jira/AzDO/Notion) shows a keyboard hint, hidden on verify."""

    def test_hint_shown_by_default(self):
        out = _render(
            _build_issue_tracking_screen(0, {0: "", 1: ""}, width=100, height=30, title_text="Notion", subtitle="Docs")
        )
        assert "Enter to verify" in out
        assert "Esc back" in out

    def test_hint_hidden_while_verifying(self):
        # border_overrides drives the verify pulse / success flash — hide the hint.
        out = _render(
            _build_issue_tracking_screen(
                0, {0: "tok"}, width=100, height=30, title_text="Notion", border_overrides={0: "rgb(1,1,1)"}
            )
        )
        assert "Enter to verify" not in out

    def test_docs_step_renders_docs_chip(self):
        # The shared form is reused for the Docs step (Notion/Confluence); step=2
        # must surface the "Docs" progress chip in the footer.
        out = _render(
            _build_issue_tracking_screen(
                0, {0: ""}, width=100, height=30, title_text="Confluence", subtitle="Docs", step=2
            )
        )
        assert "Docs" in out

    def test_active_field_shows_where_to_get_hint(self):
        # The focused field surfaces its "where to get it" hint, like the LLM and
        # GitHub steps. Field 2 = JIRA_API_TOKEN → the token-creation URL.
        out = _render(
            _build_issue_tracking_screen(2, {}, width=100, height=30, fields=_ISSUE_TRACKING_FIELDS, title_text="Jira")
        )
        assert "id.atlassian.com" in out

    def test_where_to_get_hint_hidden_while_verifying(self):
        # The verify pulse / success flash (border_overrides) should read cleanly —
        # the where-to-get hint is suppressed just like the keyboard hint.
        out = _render(
            _build_issue_tracking_screen(
                2,
                {},
                width=100,
                height=30,
                fields=_ISSUE_TRACKING_FIELDS,
                title_text="Jira",
                border_overrides={2: "rgb(1,1,1)"},
            )
        )
        assert "id.atlassian.com" not in out

    def test_error_replaces_where_to_get_hint(self):
        # A validation error on the active field takes the slot instead of the hint.
        out = _render(
            _build_issue_tracking_screen(
                2,
                {},
                width=100,
                height=30,
                fields=_ISSUE_TRACKING_FIELDS,
                title_text="Jira",
                errors={2: "Invalid token"},
            )
        )
        assert "Invalid token" in out
        assert "id.atlassian.com" not in out


class TestConnectionFieldHints:
    """Every connection field carries a non-empty 'where to get it' hint."""

    @pytest.mark.parametrize(
        "fields",
        [_ISSUE_TRACKING_FIELDS, _AZDEVOPS_TRACKING_FIELDS, _NOTION_FIELDS, _CONFLUENCE_FIELDS],
    )
    def test_all_fields_have_hints(self, fields):
        for field in fields:
            assert field.get("hint"), f"{field['env_var']} is missing a where-to-get-it hint"


class TestHintStyling:
    """`_build_hint_text` renders the info glyph + emphasized URL treatment."""

    def test_glyph_prefixes_the_line(self):
        t = _build_hint_text("Create at: id.atlassian.com/x/api-tokens")
        assert t.plain.startswith("ⓘ")

    def test_url_is_emphasized_and_underlined(self):
        t = _build_hint_text("Create at: id.atlassian.com/x/api-tokens")
        # The URL token keeps its plain text intact...
        assert "id.atlassian.com/x/api-tokens" in t.plain
        # ...and is rendered underlined (emphasis) via a dedicated span.
        assert any("underline" in str(s.style) for s in t.spans)

    def test_https_url_emphasized(self):
        t = _build_hint_text("Your org — https://dev.azure.com/<your-org>")
        assert any("underline" in str(s.style) and "dev.azure.com" in t.plain[s.start : s.end] for s in t.spans)

    def test_trailing_prose_not_swallowed_by_url(self):
        # "notion.so/my-integrations, then share …" — the comma bounds the URL so
        # the trailing instruction stays in the muted (non-underlined) style.
        t = _build_hint_text("Create at: notion.so/my-integrations, then share your pages with it")
        underlined = [t.plain[s.start : s.end] for s in t.spans if "underline" in str(s.style)]
        assert underlined == ["notion.so/my-integrations"]

    def test_no_url_renders_without_underline(self):
        t = _build_hint_text("The email you sign in to Atlassian with")
        assert "ⓘ" in t.plain
        assert "Atlassian" in t.plain
        assert not any("underline" in str(s.style) for s in t.spans)


class TestIssueTrackingPickerNav:
    """The Issue Tracking picker also honours ←/→/F section navigation."""

    _PROVIDER = {
        "full_name": "Anthropic (Claude)",
        "name": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "provider_val": "anthropic",
        "prefix": "sk-ant-",
        "instructions": "x",
    }

    def _patch_tty(self, monkeypatch):
        import select as _select

        from yeaboi.ui.provider_select import _phase_issue_tracking as it

        class _FakeStdin:
            def fileno(self):
                return 0

            def read(self, n):
                return ""

        monkeypatch.setattr(it.sys, "stdin", _FakeStdin())
        monkeypatch.setattr(it.termios, "tcgetattr", lambda fd: None)
        monkeypatch.setattr(it.termios, "tcsetattr", lambda fd, when, attrs: None)
        monkeypatch.setattr(it.tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(_select, "select", lambda r, w, x, t: ([], [], []))

    def _run(self, monkeypatch, keys):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_issue_tracking import _run_issue_tracking

        return _run_issue_tracking(
            _console(),
            _KeySequence(keys),
            None,
            self._PROVIDER,
            "sk-ant-key",
            {"env_var": "", "name": ""},
            "",
            live=_FakeLive(),
            llm_model="claude-opus-4-8",
        )

    def test_right_arrow_navigates_to_docs(self, monkeypatch):
        # Issue Tracking is step 1 → → jumps to Docs (step 2).
        assert self._run(monkeypatch, ["right"]) == StepNav(target=2)

    def test_left_arrow_navigates_to_llm(self, monkeypatch):
        assert self._run(monkeypatch, ["left"]) == StepNav(target=0)

    def test_f_finishes(self, monkeypatch):
        assert self._run(monkeypatch, ["f"]) == StepNav(finish=True)

    def test_esc_still_returns_none(self, monkeypatch):
        assert self._run(monkeypatch, ["esc"]) is None


class TestStepNav:
    """`nav_for_key` maps ←/→/F to section jumps, clamped to the chip range."""

    def test_f_finishes_from_any_step(self):
        for step in range(4):
            assert nav_for_key("f", step) == StepNav(finish=True)
        # Upper-case F (some terminals) also finishes.
        assert nav_for_key("F", 2) == StepNav(finish=True)

    def test_left_goes_to_previous_chip(self):
        assert nav_for_key("left", 1) == StepNav(target=0)
        assert nav_for_key("left", 3) == StepNav(target=2)

    def test_right_goes_to_next_chip(self):
        assert nav_for_key("right", 0) == StepNav(target=1)
        assert nav_for_key("right", 2) == StepNav(target=3)

    def test_arrows_clamp_at_boundaries(self):
        # ← at the first chip and → at the last chip do nothing (fall through).
        assert nav_for_key("left", _STEP_LLM) is None
        assert nav_for_key("right", _LAST_STEP) is None

    def test_non_nav_keys_fall_through(self):
        for key in ("up", "down", "enter", "esc", "a", "tab", "backspace"):
            assert nav_for_key(key, 2) is None

    def test_stepnav_equality_and_defaults(self):
        assert StepNav(target=2) == StepNav(target=2)
        assert StepNav(target=2) != StepNav(target=3)
        assert StepNav(finish=True) != StepNav(target=None)
        assert StepNav(target=1).finish is False


class TestNotionPicker:
    """The Notion step offers an explicit Notion / Skip picker (like Issue Tracking)."""

    def _patch_tty(self, monkeypatch):
        import select as _select

        from yeaboi.ui.provider_select import _phase_notion as pn

        class _FakeStdin:
            def fileno(self):
                return 0

            def read(self, n):
                return ""

        monkeypatch.setattr(pn.sys, "stdin", _FakeStdin())
        monkeypatch.setattr(pn.termios, "tcgetattr", lambda fd: None)
        monkeypatch.setattr(pn.termios, "tcsetattr", lambda fd, when, attrs: None)
        monkeypatch.setattr(pn.tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(_select, "select", lambda r, w, x, t: ([], [], []))

    def test_skip_returns_empty_dict(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_notion import _run_notion

        live = _FakeLive()
        # ↓ moves to "Skip", Enter selects it.
        result = _run_notion(_console(), _KeySequence(["down", "enter"]), None, live)
        assert result == {}
        # The picker screen rendered (tall Notion title + a "choose" affordance).
        rendered = "".join(_render(f) for f in live.frames)
        assert "█" in rendered and "choose" in rendered

    def test_esc_on_picker_returns_none(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_notion import _run_notion

        assert _run_notion(_console(), _KeySequence(["esc"]), None, _FakeLive()) is None

    def test_right_arrow_navigates_to_version_control(self, monkeypatch):
        # Docs is step 2 → → jumps to Version Control (step 3).
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_notion import _run_notion

        result = _run_notion(_console(), _KeySequence(["right"]), None, _FakeLive())
        assert result == StepNav(target=3)

    def test_left_arrow_navigates_to_issue_tracking(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_notion import _run_notion

        result = _run_notion(_console(), _KeySequence(["left"]), None, _FakeLive())
        assert result == StepNav(target=1)

    def test_f_finishes(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_notion import _run_notion

        result = _run_notion(_console(), _KeySequence(["f"]), None, _FakeLive())
        assert result == StepNav(finish=True)


def _active_progress_label(step: int) -> str | None:
    """Return the label of the chip _build_progress marks active for *step*.

    The active chip is styled ``bold white on <accent>`` (see _build_progress);
    the done chips use a green bg and future chips a dim grey bg, so the accent
    background uniquely identifies the active step. This lets the test assert the
    full step→chip mapping without depending on exact colour constants.
    """
    text = _build_progress(step)
    for span in text.spans:
        if "on rgb(70,100,180)" in str(span.style):
            return text.plain[span.start : span.end].strip()
    return None


class TestProgressSteps:
    """The setup wizard's progress bar has a dedicated 'Docs' chip, correctly indexed."""

    def test_steps_order(self):
        assert _STEPS == ["LLM Provider", "Issue Tracking", "Docs", "Version Control"]

    @pytest.mark.parametrize(
        "step,label",
        [
            (0, "LLM Provider"),
            (1, "Issue Tracking"),
            (2, "Docs"),
            (3, "Version Control"),
        ],
    )
    def test_active_chip_matches_step(self, step, label):
        # Regression guard for the step re-indexing: the Notion/Confluence (Docs)
        # step must highlight "Docs", not "Version Control" (the original bug).
        assert _active_progress_label(step) == label


class TestConfluenceVerify:
    """_verify_confluence checks a space is reachable with the shared Jira Atlassian auth."""

    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200))
        ok, msg = _verify_confluence("https://org.atlassian.net", "u@x.com", "tok", "SPACE")
        assert ok is True
        assert "verified" in msg.lower()

    def test_bad_credentials(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(401))
        ok, msg = _verify_confluence("https://org.atlassian.net", "u@x.com", "bad", "SPACE")
        assert ok is False
        assert "credentials" in msg.lower()

    def test_space_not_found(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_confluence("https://org.atlassian.net", "u@x.com", "tok", "NOPE")
        assert ok is False
        assert "NOPE" in msg

    def test_connection_error(self, monkeypatch):
        import httpx

        def _boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(httpx, "get", _boom)
        ok, msg = _verify_confluence("https://org.atlassian.net", "u@x.com", "tok", "SPACE")
        assert ok is False
        assert "Connection error" in msg


class TestConfluencePicker:
    """The Docs step's Confluence sub-step offers an explicit Confluence / Skip picker."""

    _JIRA = {
        "JIRA_BASE_URL": "https://org.atlassian.net",
        "JIRA_EMAIL": "u@x.com",
        "JIRA_API_TOKEN": "tok",
    }

    def _patch_tty(self, monkeypatch):
        import select as _select

        from yeaboi.ui.provider_select import _phase_confluence as pc

        class _FakeStdin:
            def fileno(self):
                return 0

            def read(self, n):
                return ""

        monkeypatch.setattr(pc.sys, "stdin", _FakeStdin())
        monkeypatch.setattr(pc.termios, "tcgetattr", lambda fd: None)
        monkeypatch.setattr(pc.termios, "tcsetattr", lambda fd, when, attrs: None)
        monkeypatch.setattr(pc.tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(_select, "select", lambda r, w, x, t: ([], [], []))

    def test_skip_returns_empty_dict(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_confluence import _run_confluence

        live = _FakeLive()
        # ↓ moves to "Skip", Enter selects it.
        result = _run_confluence(_console(), _KeySequence(["down", "enter"]), None, live, jira_creds=self._JIRA)
        assert result == {}
        rendered = "".join(_render(f) for f in live.frames)
        assert "█" in rendered and "choose" in rendered

    def test_esc_on_picker_returns_none(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_confluence import _run_confluence

        result = _run_confluence(_console(), _KeySequence(["esc"]), None, _FakeLive(), jira_creds=self._JIRA)
        assert result is None

    def test_right_arrow_navigates_to_version_control(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_confluence import _run_confluence

        result = _run_confluence(_console(), _KeySequence(["right"]), None, _FakeLive(), jira_creds=self._JIRA)
        assert result == StepNav(target=3)

    def test_f_finishes(self, monkeypatch):
        self._patch_tty(monkeypatch)
        from yeaboi.ui.provider_select._phase_confluence import _run_confluence

        result = _run_confluence(_console(), _KeySequence(["f"]), None, _FakeLive(), jira_creds=self._JIRA)
        assert result == StepNav(finish=True)


class TestShadowWordmarks:
    @pytest.mark.parametrize("word", ["ANTHROPIC", "OPENAI", "GEMINI", "BEDROCK", "GITHUB", "NOTION", "JIRA", "SETUP"])
    def test_baked_wordmark_rows_equal_width(self, word):
        rows = get_shadow_wordmark(word)
        assert rows is not None and len(rows) == 6
        assert len({len(r) for r in rows}) == 1  # all rows same width
        assert any("█" in r for r in rows)


# ---------------------------------------------------------------------------
# Data integrity — preset defaults must match _PROVIDER_DEFAULTS
# ---------------------------------------------------------------------------


class TestModelDataIntegrity:
    @pytest.mark.parametrize("card", _PROVIDER_CARDS, ids=lambda c: c["provider_val"])
    def test_default_matches_provider_defaults(self, card):
        default = card["models"]["default"]
        assert default == _PROVIDER_DEFAULTS[card["provider_val"]]
        # The default is always offered as a preset the user can pick.
        assert default in card["models"]["presets"]


# ---------------------------------------------------------------------------
# Wizard propagation — LLM_MODEL is written when select_provider returns it
# ---------------------------------------------------------------------------


class TestWizardModelPropagation:
    def _patch_config_file(self, monkeypatch, tmp_path):
        config_file = tmp_path / ".env"
        monkeypatch.setattr("yeaboi.setup_wizard.get_config_file", lambda: config_file)
        monkeypatch.setattr("yeaboi.config.get_config_file", lambda: config_file)
        return config_file

    def test_llm_model_written_to_env(self, monkeypatch, tmp_path):
        config_file = self._patch_config_file(monkeypatch, tmp_path)
        result = dict(_PROVIDERS["1"])
        result["api_key"] = "sk-ant-key"
        result["llm_model"] = "claude-opus-4-8"
        monkeypatch.setattr("yeaboi.setup_wizard.select_provider", lambda *a, **kw: result)
        console = Console(file=StringIO(), highlight=False)
        run_setup_wizard(console)
        content = config_file.read_text()
        assert "LLM_MODEL=claude-opus-4-8" in content

    def test_no_llm_model_leaves_env_unset(self, monkeypatch, tmp_path):
        config_file = self._patch_config_file(monkeypatch, tmp_path)
        result = dict(_PROVIDERS["1"])
        result["api_key"] = "sk-ant-key"  # no llm_model key
        monkeypatch.setattr("yeaboi.setup_wizard.select_provider", lambda *a, **kw: result)
        console = Console(file=StringIO(), highlight=False)
        run_setup_wizard(console)
        content = config_file.read_text()
        assert "LLM_MODEL" not in content


# ---------------------------------------------------------------------------
# fetch_available_models — live discovery (the anti-staleness mechanism)
# ---------------------------------------------------------------------------


class TestFetchAvailableModels:
    def test_anthropic_returns_ids_in_order(self, monkeypatch):
        import httpx

        payload = {"data": [{"id": "claude-opus-4-8"}, {"id": "claude-sonnet-4-6"}]}
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, payload))
        assert fetch_available_models(_card("anthropic"), "sk-ant-key") == [
            "claude-opus-4-8",
            "claude-sonnet-4-6",
        ]

    def test_openai_filters_noise_newest_first(self, monkeypatch):
        import httpx

        payload = {
            "data": [
                {"id": "gpt-4o", "created": 100},
                {"id": "text-embedding-3-large", "created": 90},
                {"id": "whisper-1", "created": 80},
                {"id": "gpt-5.6", "created": 200},
                {"id": "dall-e-3", "created": 70},
                {"id": "o1", "created": 150},
            ]
        }
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, payload))
        result = fetch_available_models(_card("openai"), "sk-key")
        # embeddings/whisper/dall-e dropped; chat models newest-first by `created`.
        assert result == ["gpt-5.6", "o1", "gpt-4o"]

    def test_google_keeps_only_generate_content(self, monkeypatch):
        import httpx

        payload = {
            "models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
            ]
        }
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, payload))
        result = fetch_available_models(_card("google"), "AIzaKey")
        assert result == ["gemini-2.5-flash", "gemini-2.5-pro"]

    def test_non_200_returns_empty(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(401))
        assert fetch_available_models(_card("anthropic"), "sk-ant-key") == []

    def test_network_error_returns_empty(self, monkeypatch):
        import httpx

        def _boom(*a, **kw):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(httpx, "get", _boom)
        assert fetch_available_models(_card("openai"), "sk-key") == []

    def test_bedrock_excluded(self):
        # No API key model listing for Bedrock — returns [] without any call.
        assert fetch_available_models(_card("bedrock"), "us-east-1") == []
