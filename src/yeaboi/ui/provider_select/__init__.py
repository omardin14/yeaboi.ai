"""Full-screen provider selection screen using Rich Live + raw terminal input.

# See README: "Architecture" — this is a UI component in the CLI layer.
# It uses Rich's Live display to redraw the full screen on each keypress,
# and reads raw keypresses via sys.stdin in cbreak/raw mode.

The screen shows three provider names as ASCII art text, stacked vertically.
Arrow keys navigate, Enter selects, q/Esc cancels.
After selection, unselected providers animate away and an API key input fades in.
Transitions between states use a common fade animation pattern.
"""

from __future__ import annotations

import logging
import math
import time

from rich.console import Console

from yeaboi.ui.provider_select._config import _save_progress  # noqa: F401
from yeaboi.ui.provider_select._constants import _PROVIDER_CARDS, _VC_OPTIONS
from yeaboi.ui.provider_select._nav import StepNav, nav_for_key
from yeaboi.ui.provider_select._phase_confluence import _run_confluence  # noqa: F401
from yeaboi.ui.provider_select._phase_docs import _run_docs
from yeaboi.ui.provider_select._phase_issue_tracking import _run_issue_tracking  # noqa: F401
from yeaboi.ui.provider_select._phase_notion import _run_notion  # noqa: F401
from yeaboi.ui.provider_select._transitions import _transition_to_input  # noqa: F401
from yeaboi.ui.provider_select._verification import (
    _verify_api_key,
    _verify_model,
    _verify_vc_token,
    fetch_available_models,
)
from yeaboi.ui.provider_select.screens._screens import (
    _build_input_screen,
    _build_model_input_screen,
    _build_model_loading_screen,
    _build_model_select_screen,
    _build_select_screen,
)
from yeaboi.ui.provider_select.screens._screens_vc import (
    _build_vc_input_screen,
    _build_vc_select_screen,
)
from yeaboi.ui.shared._animations import COLOR_RGB, FADE_IN_LEVELS, FADE_OUT_LEVELS, FRAME_TIME_30FPS

# Ctrl+V response for token/model fields — their content never reaches an LLM,
# so image paste is rejected with the standard notice (see ui/shared/_attachments.py).
from yeaboi.ui.shared._attachments import UNSUPPORTED_MESSAGE as _IMG_UNSUPPORTED
from yeaboi.ui.shared._input import disable_bracketed_paste, enable_bracketed_paste
from yeaboi.ui.shared._input import read_key as _read_key  # noqa: F401 — re-export for compat
from yeaboi.ui.shared._music_bar import make_live

logger = logging.getLogger(__name__)

# Cap the live-discovered model list so the (non-scrolling) select screen stays
# usable; "Custom…" covers anything beyond the newest few.
_MAX_LIVE_MODELS = 8


def _detect_aws_region() -> str | None:
    """Auto-detect AWS region from environment, config, or instance metadata.

    Uses boto3's built-in resolution chain which covers:
    1. AWS_REGION / AWS_DEFAULT_REGION env vars
    2. ~/.aws/config (all profile formats including [profile name])
    3. EC2/Lightsail instance metadata (IMDSv1 + IMDSv2)

    Falls back to manual parsing if boto3 is not installed.
    """
    import os

    # 1. Env vars (fast path, no imports needed)
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        return region

    # 2. boto3 session — handles ~/.aws/config and IMDS natively
    try:
        import boto3

        session = boto3.session.Session()
        if session.region_name:
            return session.region_name
    except Exception:
        pass

    # 3. Manual fallback — parse ~/.aws/config directly
    try:
        from pathlib import Path

        config_path = Path.home() / ".aws" / "config"
        if config_path.exists():
            for line in config_path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("region"):
                    _, _, value = stripped.partition("=")
                    if value.strip():
                        return value.strip()
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_provider(
    console: Console | None = None, *, _read_key_fn=None, existing_config: dict[str, str] | None = None
) -> dict[str, str] | None:
    """Show full-screen provider selection, then API key input with verification.

    Organized as a step-based loop:
    Step 0: LLM Provider selection + API key verification
    Step 1: Issue Tracking (Jira / Azure DevOps Boards / Skip)
    Step 2: Docs — Notion (own token) then Confluence (shares Jira's Atlassian
            auth, so only shown when Jira was configured). Both optional.
    Step 3: Version Control (GitHub PAT)

    Navigation: Enter advances / confirms and Esc steps back, as before. Step 0
    (LLM) is a required gate — the returned config dict is seeded from the chosen
    provider + key. Once past it, the section chips act as a tab bar: on any
    section's picker, ← / → jump between Issue Tracking, Docs and Version Control
    (and back to LLM) in any order, and F finishes the wizard from anywhere.
    Choices are accumulated in a single dict so jumping around never loses them.

    Returns a dict compatible with setup_wizard._PROVIDERS values (with an
    added 'api_key' field), or None if the user cancelled.
    """
    console = console or Console()
    read_key = _read_key_fn or _read_key

    # Enable bracketed paste mode so the terminal wraps pasted text in
    # \x1b[200~ ... \x1b[201~ markers. _read_key detects these and returns
    # the full pasted content as a single "paste:..." string.
    enable_bracketed_paste()

    import inspect

    _supports_timeout = "timeout" in inspect.signature(read_key).parameters

    # State preserved across steps (so going back retains previous choices)
    provider = None
    api_key = ""
    llm_model = ""
    vc = None
    vc_token = ""
    step = 0

    # The single accumulator for everything the wizard collects. Seeded once the
    # LLM step completes (see step 0) and then updated slice-by-slice by each
    # section, so the user can visit Issue Tracking / Docs / Version Control in
    # any order (← / → between chips) and finish (F) from anywhere without losing
    # what earlier sections gathered. Returned to setup_wizard as the result.
    _collected: dict[str, str] = {}
    # Set when a StepNav jump lands us on a section, so that section skips its
    # cinematic fade-in transition (which assumes we arrived from the prior step).
    _via_nav = False

    w, h = console.size
    with make_live(
        _build_select_screen(0, width=w, height=h, shimmer_tick=0.0),
        console=console,
        refresh_per_second=30,
        screen=True,
    ) as live:
        # Cinematic entrance — a fade-in + shine "SETUP" wordmark, matching the
        # per-mode intros, so first-run / --setup / Settings→Configure feel branded.
        from yeaboi.ui.splash import play_wordmark_intro

        play_wordmark_intro(console, live, "Setup", (70, 100, 180), frame_time=1.0 / 30)

        def _run_model_phase(api_key_val: str) -> str | None:
            """Model-selection sub-step of Step 0.

            Shows a list of the provider's preset models (plus any detected/current
            model and a "Custom…" entry). Validates the chosen or typed model with a
            live call so we never save a model the credentials can't run.

            Returns the validated model id, or None if the user pressed Esc to go back
            to the API-key input.
            """
            models_cfg = provider.get("models") or {}
            presets = list(models_cfg.get("presets") or [])
            default_model = models_cfg.get("default", "")

            # Live discovery: ask the provider what this key can actually run, so
            # the menu never offers a retired id. The hardcoded presets above are
            # only an offline seed. Bedrock is excluded (auto-detects via OpenClaw).
            if provider.get("provider_val") != "bedrock" and api_key_val:
                # Run the (blocking, up-to-8s) HTTP discovery on a daemon thread while
                # the Live loop keeps animating a "Discovering…" screen — otherwise the
                # render loop freezes and the user stares at a frozen frame. Same
                # threaded-pulse pattern as _verify_pulsing and the verify loops.
                import threading

                discovered_box: list[list[str]] = []

                def _do_discover() -> None:
                    discovered_box.append(fetch_available_models(provider, api_key_val))

                thread = threading.Thread(target=_do_discover, daemon=True)
                thread.start()
                disc_start = time.monotonic()
                while thread.is_alive():
                    w, h = console.size
                    tick = time.monotonic() - disc_start
                    live.update(_build_model_loading_screen(provider, tick, width=w, height=h))
                    time.sleep(FRAME_TIME_30FPS)
                thread.join()
                discovered = discovered_box[0] if discovered_box else []
                logger.debug("provider_select: discovered %d models for %s", len(discovered), provider["provider_val"])
                if discovered:
                    presets = discovered[:_MAX_LIVE_MODELS]

            # A detected Bedrock model (from OpenClaw) or a previously-saved LLM_MODEL
            # is offered at the top of the list and pre-selected, preserving zero-config.
            detected = None
            if provider.get("provider_val") == "bedrock":
                try:
                    from yeaboi.setup_wizard import _detect_openclaw_bedrock_model

                    detected = _detect_openclaw_bedrock_model()
                except Exception:
                    detected = None
            existing_model = (existing_config or {}).get("LLM_MODEL", "")

            model_ids: list[str] = []  # actual model id per entry ("" marks Custom…)
            labels: list[str] = []  # display label per entry

            def _add(mid: str, tag: str = "") -> None:
                if mid and mid not in model_ids:
                    model_ids.append(mid)
                    labels.append(f"{mid}  {tag}" if tag else mid)

            _add(detected, "(detected)")
            _add(existing_model, "(current)")
            for m in presets:
                _add(m)
            model_ids.append("")  # Custom… sentinel
            labels.append("Custom…")

            pre = detected or existing_model or default_model
            selected = model_ids.index(pre) if pre in model_ids else 0

            def _verify_pulsing(model_id: str, render) -> tuple[bool, str]:
                """Run _verify_model on a thread while `render(border_style)` pulses."""
                import threading

                result: list[tuple[bool, str]] = []

                def _do() -> None:
                    result.append(_verify_model(provider, api_key_val, model_id))

                thread = threading.Thread(target=_do, daemon=True)
                thread.start()
                pulse_start = time.monotonic()
                while thread.is_alive():
                    elapsed = time.monotonic() - pulse_start
                    intensity = (math.sin(elapsed * 6) + 1) / 2
                    v = int(60 + 140 * intensity)
                    render(f"rgb({v},{v},{v})")
                    time.sleep(FRAME_TIME_30FPS)
                thread.join()
                return result[0]

            def _run_custom_input() -> str | None:
                """Text-input loop for a typed model id. Returns id or None (back)."""
                val = existing_model if existing_model not in presets else ""
                err = ""
                verified: bool | None = None
                while True:
                    w, h = console.size
                    live.update(
                        _build_model_input_screen(provider, val, width=w, height=h, error=err, verified=verified)
                    )
                    key = read_key()
                    if key == "enter":
                        if not val.strip():
                            err = "Model id is required"
                            verified = False
                            continue
                        model_id = val.strip()

                        def _render(border: str) -> None:
                            w2, h2 = console.size
                            live.update(
                                _build_model_input_screen(
                                    provider, val, width=w2, height=h2, verifying=True, border_override=border
                                )
                            )

                        ok, msg = _verify_pulsing(model_id, _render)
                        if ok:
                            logger.info("LLM model verified (custom): %s", model_id)
                            w, h = console.size
                            live.update(_build_model_input_screen(provider, val, width=w, height=h, verified=True))
                            time.sleep(0.5)
                            return model_id
                        logger.warning("LLM model verification failed (custom): %s — %s", model_id, msg)
                        err = msg
                        verified = False
                    elif key == "esc":
                        return None
                    elif key == "clear":
                        val = ""
                        err = ""
                        verified = None
                    elif key == "backspace":
                        val = val[:-1]
                        err = ""
                        verified = None
                    elif key.startswith("paste:"):
                        val += key[6:]
                        err = ""
                        verified = None
                    elif key == "ctrl+v":
                        err = _IMG_UNSUPPORTED
                    elif len(key) == 1 and key.isprintable():
                        val += key
                        err = ""
                        verified = None

            # Preset-list selection loop.
            err = ""
            start_time = time.monotonic()
            while True:
                w, h = console.size
                tick = time.monotonic() - start_time
                live.update(
                    _build_model_select_screen(
                        provider, labels, selected, width=w, height=h, shimmer_tick=tick, error=err
                    )
                )
                key = read_key(timeout=FRAME_TIME_30FPS) if _supports_timeout else read_key()
                if key in ("up", "scroll_up"):
                    selected = (selected - 1) % len(labels)
                    err = ""
                elif key in ("down", "scroll_down"):
                    selected = (selected + 1) % len(labels)
                    err = ""
                elif key == "enter":
                    chosen_id = model_ids[selected]
                    if chosen_id == "":  # Custom…
                        typed = _run_custom_input()
                        if typed is not None:
                            return typed
                        continue  # Esc from custom input → back to preset list
                    logger.info("LLM model chosen (preset): %s", chosen_id)

                    def _render(_border: str) -> None:
                        w2, h2 = console.size
                        live.update(_build_model_select_screen(provider, labels, selected, width=w2, height=h2))

                    ok, msg = _verify_pulsing(chosen_id, _render)
                    if ok:
                        logger.info("LLM model verified (preset): %s", chosen_id)
                        return chosen_id
                    logger.warning("LLM model verification failed (preset): %s — %s", chosen_id, msg)
                    err = msg
                elif key in ("q", "esc"):
                    return None

        while step < 4:
            # ══════════════════════════════════════════════════════════════
            # Step 0: LLM Provider selection + API key input
            # ══════════════════════════════════════════════════════════════
            if step == 0:
                selected = 0
                n = len(_PROVIDER_CARDS)
                start_time = time.monotonic()

                w, h = console.size
                live.update(_build_select_screen(selected, width=w, height=h, shimmer_tick=0.0))

                # Phase 1: Provider selection
                _step0_done = False
                while True:
                    key = read_key(timeout=FRAME_TIME_30FPS) if _supports_timeout else read_key()
                    if key in ("up", "scroll_up"):
                        selected = (selected - 1) % n
                    elif key in ("down", "scroll_down"):
                        selected = (selected + 1) % n
                    elif key == "enter":
                        break
                    elif key in ("q", "esc"):
                        logger.info("provider_select: cancelled at LLM provider selection")
                        disable_bracketed_paste()
                        return None
                    w, h = console.size
                    tick = time.monotonic() - start_time
                    live.update(_build_select_screen(selected, width=w, height=h, shimmer_tick=tick))

                # Transition animation
                provider = _PROVIDER_CARDS[selected]
                logger.info("provider_select: LLM provider chosen: %s", provider["full_name"])
                _transition_to_input(live, console, selected, provider)

                # Phase 2: API key input
                _cfg = existing_config or {}
                input_value = _cfg.get(provider["env_var"], "")
                if provider.get("is_region_input") and not input_value:
                    input_value = _detect_aws_region() or ""
                error = ""
                verified: bool | None = None

                w, h = console.size
                live.update(_build_input_screen(provider, input_value, width=w, height=h))

                while True:
                    key = read_key()
                    if key == "enter":
                        if not input_value.strip():
                            error = f"{provider['env_var']} is required."
                            w, h = console.size
                            live.update(_build_input_screen(provider, input_value, width=w, height=h, error=error))
                            continue

                        import threading

                        verify_result: list[tuple[bool, str]] = []

                        def _do_verify():
                            verify_result.append(_verify_api_key(provider, input_value.strip()))

                        logger.info("provider_select: verifying %s credentials", provider["full_name"])
                        thread = threading.Thread(target=_do_verify, daemon=True)
                        thread.start()

                        pulse_start = time.monotonic()
                        while thread.is_alive():
                            elapsed = time.monotonic() - pulse_start
                            intensity = (math.sin(elapsed * 6) + 1) / 2
                            v = int(60 + 140 * intensity)
                            w, h = console.size
                            live.update(
                                _build_input_screen(
                                    provider,
                                    input_value,
                                    width=w,
                                    height=h,
                                    verifying=True,
                                    border_override=f"rgb({v},{v},{v})",
                                )
                            )
                            time.sleep(FRAME_TIME_30FPS)

                        thread.join()
                        ok, msg = verify_result[0]
                        verified = ok
                        if ok:
                            logger.info("provider_select: %s credentials verified", provider["full_name"])
                        else:
                            logger.warning(
                                "provider_select: %s credential verification failed — %s",
                                provider["full_name"],
                                msg,
                            )

                        if ok:
                            green_r, green_g, green_b = 80, 220, 120
                            for frame in range(10):
                                t = frame / 9
                                intensity = math.sin(t * math.pi)
                                r = int(green_r + (255 - green_r) * intensity)
                                g = int(green_g + (255 - green_g) * intensity)
                                b = int(green_b + (255 - green_b) * intensity)
                                w, h = console.size
                                live.update(
                                    _build_input_screen(
                                        provider,
                                        input_value,
                                        width=w,
                                        height=h,
                                        verified=True,
                                        border_override=f"rgb({r},{g},{b})",
                                    )
                                )
                                time.sleep(FRAME_TIME_30FPS)

                            w, h = console.size
                            live.update(_build_input_screen(provider, input_value, width=w, height=h, verified=True))
                            time.sleep(0.6)
                            api_key = input_value.strip()
                            _save_progress({"LLM_PROVIDER": provider["provider_val"], provider["env_var"]: api_key})

                            # Model-selection sub-step. Esc returns None → fall back
                            # to this API-key input loop (context preserved).
                            chosen_model = _run_model_phase(api_key)
                            if chosen_model is not None:
                                llm_model = chosen_model
                                _save_progress({"LLM_MODEL": chosen_model})
                                _step0_done = True
                                break
                            # Back from model phase — re-show the verified key input.
                            w, h = console.size
                            live.update(_build_input_screen(provider, input_value, width=w, height=h, verified=True))
                            continue
                        else:
                            w, h = console.size
                            live.update(
                                _build_input_screen(
                                    provider,
                                    input_value,
                                    width=w,
                                    height=h,
                                    verified=False,
                                    error=msg,
                                )
                            )
                        continue

                    elif key == "esc":
                        # Go back to provider selection — restart step 0
                        break
                    elif key == "clear":
                        input_value = ""
                        error = ""
                        verified = None
                    elif key == "backspace":
                        input_value = input_value[:-1]
                        error = ""
                        verified = None
                    elif key.startswith("paste:"):
                        input_value += key[6:]
                        error = ""
                        verified = None
                    elif key == "ctrl+v":
                        error = _IMG_UNSUPPORTED
                    elif len(key) == 1 and key.isprintable():
                        input_value += key
                        error = ""
                        verified = None
                    w, h = console.size
                    live.update(
                        _build_input_screen(
                            provider,
                            input_value,
                            width=w,
                            height=h,
                            error=error,
                            verified=verified,
                        )
                    )

                if _step0_done:
                    # Seed the accumulator from the LLM choice. setdefault keeps any
                    # slices (issue_tracking/notion/confluence/vc) already gathered on
                    # a prior visit, so re-doing the LLM step to change providers never
                    # wipes the other sections' data.
                    _collected.update(
                        {
                            "name": provider["full_name"],
                            "env_var": provider["env_var"],
                            "provider_val": provider["provider_val"],
                            "prefix": provider["prefix"],
                            "instructions": provider["instructions"],
                            "api_key": api_key,
                            "llm_model": llm_model,
                        }
                    )
                    _collected.setdefault("issue_tracking", {})
                    logger.info(
                        "provider_select: LLM step complete (provider=%s, model=%s)",
                        provider["provider_val"],
                        llm_model,
                    )
                    step = 1
                    _via_nav = False
                # else: Esc pressed → loop restarts step 0
                continue

            # ══════════════════════════════════════════════════════════════
            # Step 1: Issue Tracking (Jira / Azure DevOps Boards / Skip)
            # ══════════════════════════════════════════════════════════════
            elif step == 1:
                _arrived_nav = _via_nav
                _via_nav = False
                # Fade out LLM input, fade in issue tracking. Skipped when we
                # arrived via a ←/→ jump (there's no LLM input to fade from).
                if not _arrived_nav:
                    for grey in FADE_OUT_LEVELS:
                        w, h = console.size
                        live.update(_build_input_screen(provider, api_key, width=w, height=h, input_fade=grey))
                        time.sleep(FRAME_TIME_30FPS)

                # vc/vc_token not known yet — pass placeholders
                _dummy_vc = {"env_var": "", "name": ""}
                result = _run_issue_tracking(
                    console,
                    read_key,
                    existing_config,
                    provider,
                    api_key,
                    _dummy_vc,
                    "",
                    live=live,
                    llm_model=llm_model,
                )

                if isinstance(result, StepNav):
                    if result.finish:
                        logger.info("provider_select: wizard finished (from issue tracking)")
                        disable_bracketed_paste()
                        return _collected
                    step = result.target
                    _via_nav = True
                elif result is not None:
                    _collected.update(result)
                    step = 2
                else:
                    step = 0  # Esc → go back to LLM provider
                continue

            # ══════════════════════════════════════════════════════════════
            # Step 2: Docs (Notion + Confluence, both optional)
            # ══════════════════════════════════════════════════════════════
            elif step == 2:
                _arrived_nav = _via_nav
                _via_nav = False
                # Fade out the previous screen into the Notion form. Skipped on a
                # ←/→ jump (there's no prior input screen to fade from).
                if not _arrived_nav:
                    for grey in FADE_OUT_LEVELS:
                        w, h = console.size
                        live.update(_build_input_screen(provider, api_key, width=w, height=h, input_fade=grey))
                        time.sleep(FRAME_TIME_30FPS)

                # One unified Docs picker (Notion / Confluence / Skip), mirroring the
                # Issue Tracking step. Confluence is a first-class option here: it
                # reuses the Jira Atlassian creds when they were collected in step 1,
                # otherwise its form collects a standalone Atlassian login inline.
                _jira_creds = _collected.get("issue_tracking", {})
                docs_result = _run_docs(console, read_key, existing_config, live, jira_creds=_jira_creds)
                if isinstance(docs_result, StepNav):
                    if docs_result.finish:
                        logger.info("provider_select: wizard finished (from docs)")
                        disable_bracketed_paste()
                        return _collected
                    step = docs_result.target
                    _via_nav = True
                    continue
                if docs_result is None:
                    step = 1  # Esc → go back to issue tracking
                    continue
                # Empty dicts = user skipped (optional). Either way, record both slices.
                _collected["notion"] = docs_result["notion"]
                _collected["confluence"] = docs_result["confluence"]

                step = 3
                continue

            # ══════════════════════════════════════════════════════════════
            # Step 3: Version Control (GitHub PAT)
            # ══════════════════════════════════════════════════════════════
            elif step == 3:
                _arrived_nav = _via_nav
                _via_nav = False
                vc_selected = 0
                vc_n = len(_VC_OPTIONS)
                vc_start = time.monotonic()

                if not _arrived_nav:
                    for grey in FADE_IN_LEVELS:
                        w, h = console.size
                        live.update(
                            _build_vc_select_screen(
                                vc_selected,
                                width=w,
                                height=h,
                                fade_style=grey,
                                fade_indices=list(range(vc_n)),
                            )
                        )
                        time.sleep(FRAME_TIME_30FPS)

                # VC selection loop
                _step2_selected = False
                _vc_nav: StepNav | None = None
                while True:
                    key = read_key(timeout=FRAME_TIME_30FPS) if _supports_timeout else read_key()
                    # Section navigation (←/→ between chips, F to finish) short-circuits
                    # the picker just like the other sections.
                    nav = nav_for_key(key, 3)
                    if nav is not None:
                        _vc_nav = nav
                        break
                    if key in ("up", "scroll_up"):
                        vc_selected = (vc_selected - 1) % vc_n
                    elif key in ("down", "scroll_down"):
                        vc_selected = (vc_selected + 1) % vc_n
                    elif key == "enter":
                        _step2_selected = True
                        break
                    elif key in ("q", "esc"):
                        break  # go back
                    w, h = console.size
                    tick = time.monotonic() - vc_start
                    live.update(_build_vc_select_screen(vc_selected, width=w, height=h, shimmer_tick=tick))

                if _vc_nav is not None:
                    if _vc_nav.finish:
                        logger.info("provider_select: wizard finished (from version control)")
                        disable_bracketed_paste()
                        return _collected
                    step = _vc_nav.target
                    _via_nav = True
                    continue

                if not _step2_selected:
                    step = 1
                    continue

                vc = _VC_OPTIONS[vc_selected]
                logger.info("provider_select: version control chosen: %s", vc["name"])

                # Skip selected — no PAT needed, finish wizard
                if not vc["env_var"]:
                    logger.info("provider_select: wizard finished (version control skipped)")
                    _collected["vc_env_var"] = ""
                    _collected["vc_token"] = ""
                    disable_bracketed_paste()
                    return _collected

                # Transition: pulse selected, fade others, crossfade to input
                all_vc = list(range(vc_n))
                others_vc = [i for i in all_vc if i != vc_selected]
                base_r, base_g, base_b = COLOR_RGB.get(vc["color"], (180, 180, 180))
                base_style = f"rgb({base_r},{base_g},{base_b})"

                for frame in range(12):
                    t = frame / 11
                    intensity = math.sin(t * math.pi)
                    r = int(base_r + (255 - base_r) * intensity)
                    g = int(base_g + (255 - base_g) * intensity)
                    b = int(base_b + (255 - base_b) * intensity)
                    pulse_style = f"rgb({r},{g},{b})"
                    w, h = console.size
                    live.update(
                        _build_vc_select_screen(
                            vc_selected,
                            width=w,
                            height=h,
                            visible=all_vc,
                            fade_style=pulse_style,
                            fade_indices=[vc_selected],
                        )
                    )
                    time.sleep(FRAME_TIME_30FPS)

                for grey in FADE_OUT_LEVELS:
                    w, h = console.size
                    live.update(
                        _build_vc_select_screen(
                            vc_selected,
                            width=w,
                            height=h,
                            visible=all_vc,
                            fade_style=grey,
                            fade_indices=others_vc,
                            selected_style=base_style,
                        )
                    )
                    time.sleep(FRAME_TIME_30FPS)

                for grey in FADE_IN_LEVELS:
                    w, h = console.size
                    live.update(_build_vc_input_screen(vc, "", width=w, height=h, input_fade=grey))
                    time.sleep(FRAME_TIME_30FPS)
                w, h = console.size
                live.update(_build_vc_input_screen(vc, "", width=w, height=h))

                # PAT token input
                _cfg = existing_config or {}
                vc_input = _cfg.get(vc["env_var"], "")
                vc_error = ""
                vc_verified: bool | None = None
                _step2_done = False

                while True:
                    key = read_key()
                    if key == "enter":
                        if not vc_input.strip():
                            vc_error = f"{vc['env_var']} is required."
                            w, h = console.size
                            live.update(_build_vc_input_screen(vc, vc_input, width=w, height=h, error=vc_error))
                            continue

                        import threading

                        verify_result: list[tuple[bool, str]] = []

                        def _do_vc_verify():
                            verify_result.append(_verify_vc_token(vc, vc_input.strip()))

                        logger.info("provider_select: verifying %s token", vc["name"])
                        thread = threading.Thread(target=_do_vc_verify, daemon=True)
                        thread.start()

                        pulse_start = time.monotonic()
                        while thread.is_alive():
                            elapsed = time.monotonic() - pulse_start
                            intensity = (math.sin(elapsed * 6) + 1) / 2
                            v = int(60 + 140 * intensity)
                            w, h = console.size
                            live.update(
                                _build_vc_input_screen(
                                    vc,
                                    vc_input,
                                    width=w,
                                    height=h,
                                    verifying=True,
                                    border_override=f"rgb({v},{v},{v})",
                                )
                            )
                            time.sleep(FRAME_TIME_30FPS)

                        thread.join()
                        ok, msg = verify_result[0]
                        vc_verified = ok
                        if ok:
                            logger.info("provider_select: %s token verified", vc["name"])
                        else:
                            logger.warning("provider_select: %s token verification failed — %s", vc["name"], msg)

                        if ok:
                            green_r, green_g, green_b = 80, 220, 120
                            for frame in range(10):
                                t = frame / 9
                                intensity = math.sin(t * math.pi)
                                r = int(green_r + (255 - green_r) * intensity)
                                g = int(green_g + (255 - green_g) * intensity)
                                b = int(green_b + (255 - green_b) * intensity)
                                w, h = console.size
                                live.update(
                                    _build_vc_input_screen(
                                        vc,
                                        vc_input,
                                        width=w,
                                        height=h,
                                        verified=True,
                                        border_override=f"rgb({r},{g},{b})",
                                    )
                                )
                                time.sleep(FRAME_TIME_30FPS)

                            w, h = console.size
                            live.update(_build_vc_input_screen(vc, vc_input, width=w, height=h, verified=True))
                            time.sleep(0.6)
                            vc_token = vc_input.strip()
                            _save_progress({vc["env_var"]: vc_token})
                            _step2_done = True
                            break
                        else:
                            w, h = console.size
                            live.update(
                                _build_vc_input_screen(
                                    vc,
                                    vc_input,
                                    width=w,
                                    height=h,
                                    verified=False,
                                    error=msg,
                                )
                            )
                        continue

                    elif key == "esc":
                        break  # go back to step 1
                    elif key == "clear":
                        vc_input = ""
                        vc_error = ""
                        vc_verified = None
                    elif key == "backspace":
                        vc_input = vc_input[:-1]
                        vc_error = ""
                        vc_verified = None
                    elif key.startswith("paste:"):
                        vc_input += key[6:]
                        vc_error = ""
                        vc_verified = None
                    elif key == "ctrl+v":
                        vc_error = _IMG_UNSUPPORTED
                    elif len(key) == 1 and key.isprintable():
                        vc_input += key
                        vc_error = ""
                        vc_verified = None
                    w, h = console.size
                    live.update(
                        _build_vc_input_screen(
                            vc,
                            vc_input,
                            width=w,
                            height=h,
                            error=vc_error,
                            verified=vc_verified,
                        )
                    )

                if _step2_done:
                    # Build final result — merge issue tracking data with VC
                    logger.info("provider_select: wizard finished (all steps complete)")
                    _collected["vc_env_var"] = vc["env_var"]
                    _collected["vc_token"] = vc_token
                    disable_bracketed_paste()
                    return _collected
                else:
                    step = 2  # Esc → go back to Notion
                    continue

    disable_bracketed_paste()
    return None
