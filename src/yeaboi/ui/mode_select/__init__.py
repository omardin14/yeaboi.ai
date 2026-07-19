"""Full-screen mode selection screen using Rich Live + raw terminal input.

# See README: "Architecture" — this is a UI component in the CLI layer.
# Shown after the setup wizard completes (or on subsequent launches).
# The user picks which agent mode to run: Project Planning, Code Review, etc.
# After selecting Planning, the title slides up and the project list fades in.

Mode names are rendered as two-line ASCII art, stacked vertically.
When a mode is selected, its description typewriter-scrolls in underneath.
Arrow keys navigate, Enter selects. "Coming soon" modes are visible but
not selectable.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

from rich.console import Console

from yeaboi.logging_setup import attach_mode_handler, mode_log
from yeaboi.logging_setup import detach as detach_mode_handler
from yeaboi.paths import get_db_path as _get_db_path
from yeaboi.ui.mode_select.screens._project_cards import (  # noqa: F401
    ProfileSummary,
    ProjectSummary,
    _build_action_button,
    _build_empty_state_card,
    _build_new_analysis_card,
    _build_new_project_card,
    _build_peek_above,
    _build_peek_below,
    _build_profile_card,
    _build_project_card,
    _compute_viewport,
)
from yeaboi.ui.mode_select.screens._project_list_screen import (  # noqa: F401
    _build_project_list_screen,
    _build_project_row,
)

# Re-exports for backwards compatibility and test imports.
from yeaboi.ui.mode_select.screens._screens import (  # noqa: F401
    _INTAKE_CARDS,
    _MODE_CARDS,
    _OFFLINE_CARDS,
    _build_mode_screen,
    _build_slide_frame,
)
from yeaboi.ui.mode_select.screens._screens_secondary import (  # noqa: F401
    _build_export_success_screen,
    _build_import_screen,
    _build_intake_screen,
    _build_offline_screen,
    _build_project_export_success_screen,
    _build_team_analysis_screen,
)
from yeaboi.ui.shared._animations import (
    COLOR_RGB,
    FADE_IN_LEVELS,
    FADE_OUT_LEVELS,
    FRAME_TIME_60FPS,
    ease_out_cubic,
)
from yeaboi.ui.shared._input import read_key as _read_key
from yeaboi.ui.shared._music_bar import make_live
from yeaboi.ui.shared._scroll import SCROLL_KEYS, coalesce_scroll, coalesce_steps
from yeaboi.ui.splash import play_wordmark_intro

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants used only by the orchestrator
# ---------------------------------------------------------------------------

_DESC_SCROLL_SPEED = 200  # characters per second for typewriter reveal
_HEADER_SUB_SPEED = 45  # characters per second for the page subtitle typewriter reveal
_FRAME_TIME = FRAME_TIME_60FPS


def _next_log_level(current: str) -> str:
    """Return the next level in the Settings cycle: DEBUG → INFO → WARNING → ERROR → DEBUG.

    Unknown values (including CRITICAL, which is .env-only) are treated as
    WARNING, so the first press lands on ERROR.
    """
    from yeaboi.config import VALID_LOG_LEVELS

    current = current.upper()
    if current not in VALID_LOG_LEVELS:
        current = "WARNING"
    return VALID_LOG_LEVELS[(VALID_LOG_LEVELS.index(current) + 1) % len(VALID_LOG_LEVELS)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_ana_sid = ""  # module-level analysis session ID
_ana_dbp = _get_db_path()  # module-level DB path


def _load_ana_session(project_key: str) -> dict | None:
    """Load the most recent analysis session for a project, or None."""
    try:
        from yeaboi.sessions import SessionStore

        with SessionStore(_ana_dbp) as store:
            sessions = store.list_analysis_sessions()
            for sess in sessions:
                if project_key in sess.get("project_name", ""):
                    state = store.load_state(sess["session_id"])
                    if state and state.get("last_page") and state["last_page"] not in ("complete", "done", ""):
                        global _ana_sid  # noqa: PLW0603
                        _ana_sid = sess["session_id"]
                        logger.info(
                            "Resuming analysis session %s at page '%s'",
                            sess["session_id"],
                            state["last_page"],
                        )
                        return state
        logger.debug("No resumable analysis session for %s", project_key)
    except Exception:
        logger.debug("Analysis session load failed", exc_info=True)
    return None


def _save_ana(state: dict, node: str) -> None:
    """Save analysis session state (extracted to reduce nesting depth)."""
    if not _ana_sid:
        return
    try:
        from yeaboi.sessions import SessionStore

        with SessionStore(_ana_dbp) as store:
            store.save_state(_ana_sid, state)
            store.update_last_node(_ana_sid, node)
        logger.info("Analysis session saved: page='%s', session=%s", node, _ana_sid)
    except Exception:
        logger.debug("Analysis session save failed", exc_info=True)


def _confirm_ticket_generation(
    live,
    console,
    read_key,
    frame_time,
    supports_timeout,
    *,
    subtitle: str = "",
) -> bool:
    """Ask the user whether to generate sample tickets from the team analysis.

    Renders a dedicated confirmation screen (separating "analyse the team/board"
    from "create sample tickets") and drives a thin frame loop. Returns True if
    the user chooses to generate, False if they decline (Not now / Esc).
    """
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_generate_confirm_screen

    logger.info("Analysis: showing ticket-generation confirmation")
    sel = 0  # 0 = Generate tickets, 1 = Not now
    while True:
        w, h = console.size
        live.update(
            _build_generate_confirm_screen(
                width=w,
                height=h,
                action_sel=sel,
                subtitle=subtitle,
            )
        )
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if k == "left":
            sel = max(0, sel - 1)
        elif k == "right":
            sel = min(1, sel + 1)
        elif k in ("enter", " "):
            proceed = sel == 0
            logger.info("Analysis: ticket generation %s", "confirmed" if proceed else "declined")
            return proceed
        elif k in ("esc", "q"):
            logger.info("Analysis: ticket generation declined (esc)")
            return False


def _run_preview_flow(
    live,
    console,
    read_key,
    frame_time,
    supports_timeout,
    instr_text,
    ta_profile,
    ta_examples,
    *,
    resume_state: dict | None = None,
):
    """Run the analysis preview flow (Instructions → Epic → Stories → Tasks → Sprint).

    If resume_state is provided, jumps to the appropriate page.
    """
    from yeaboi.tools.team_learning import (
        generate_sample_epic,
        generate_sample_stories,
        generate_sample_tasks,
    )
    from yeaboi.ui.mode_select.screens._screens_secondary import (
        _build_analysis_progress_screen,
        _build_instructions_review_screen,
        _build_sample_epic_screen,
        _build_sample_stories_screen,
        _build_sample_tasks_screen,
    )

    # Accepts an optional timeout so coalesce_scroll() can poll non-blocking
    # (timeout=0.0); a bare _rk() keeps the original per-frame/blocking behaviour.
    _rk = lambda timeout=(frame_time if supports_timeout else None): read_key(timeout=timeout)  # noqa: E731

    # ── Inline editor helpers for dict-based artifacts ────────────
    def _dict_editable_start(line: str) -> int | None:
        """Return column where editable value starts, or None if non-editable."""
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith("\u2500\u2500") and stripped.endswith("\u2500\u2500"):
            return None
        import re as _re

        m = _re.match(r"^[A-Za-z][A-Za-z /]+:\s*", line)
        if m:
            return m.end()
        return None  # non-label lines are not editable

    def _edit_dict_artifact(artifact: dict, fields: list[str], label: str) -> dict | None:
        """Open inline editor for a dict artifact. Returns edited dict or None on cancel."""
        from yeaboi.ui.session.editor._editor_core import edit_buffer_loop, render_editor_panel
        from yeaboi.ui.shared._components import analysis_title as _a_title

        # Serialize to text
        w = max(len(f) for f in fields) + 2
        buf_lines: list[str] = []
        for f in fields:
            display_label = f.replace("_", " ").title()
            val = artifact.get(f, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            buf_lines.append(f"{display_label + ':':<{w}}{val}")
            buf_lines.append("")

        buffer = buf_lines
        cr, cc = 0, len(buffer[0].split(":")[0]) + 2 if buffer else 0
        # Find first editable position
        for i, ln in enumerate(buffer):
            col = _dict_editable_start(ln)
            if col is not None:
                cr, cc = i, col
                break
        _atitle = _a_title()

        def _render(buf, _cr, _cc, so, rw, rh):
            return render_editor_panel(
                buf,
                _cr,
                _cc,
                so,
                width=rw,
                height=rh,
                editor_label=label,
                title_override=_atitle,
            )

        result = edit_buffer_loop(
            live,
            console,
            buffer,
            cr,
            cc,
            _rk,
            editable_start_fn=_dict_editable_start,
            render_fn=_render,
        )
        if result is None:
            return None

        # Parse back: extract "Label: value" pairs
        import re as _re

        edited = dict(artifact)  # shallow copy
        for line in result:
            m = _re.match(r"^([A-Za-z][A-Za-z /]+):\s*(.*)", line)
            if m:
                key_display = m.group(1).strip()
                value = m.group(2).strip()
                # Map display label back to dict key
                key = key_display.lower().replace(" ", "_")
                if key in artifact:
                    orig = artifact[key]
                    if isinstance(orig, int):
                        try:
                            value = int(value)
                        except ValueError:
                            continue
                    elif isinstance(orig, list):
                        value = [v.strip() for v in value.split(",") if v.strip()]
                    edited[key] = value
        return edited

    def _edit_story_dict(story: dict) -> dict | None:
        """Edit a single story dict using the planning mode story editor."""
        from yeaboi.agent.state import (
            AcceptanceCriterion,
            Discipline,
            Priority,
            StoryPointValue,
            UserStory,
        )
        from yeaboi.ui.session.editor._editor import edit_story

        # Convert dict → UserStory
        acs = tuple(
            AcceptanceCriterion(given=ac.get("given", ""), when=ac.get("when", ""), then=ac.get("then", ""))
            for ac in story.get("acceptance_criteria", [])
            if isinstance(ac, dict)
        )
        pts_raw = story.get("story_points", 3)
        pts_val = pts_raw if pts_raw in (1, 2, 3, 5, 8) else 3
        pri_str = story.get("priority", "medium").lower()
        pri = Priority(pri_str) if pri_str in ("critical", "high", "medium", "low") else Priority.MEDIUM
        disc_str = story.get("discipline", "fullstack").lower()
        try:
            disc = Discipline(disc_str)
        except ValueError:
            disc = Discipline.FULLSTACK

        user_story = UserStory(
            id=story.get("id", "S1"),
            feature_id="F1",
            persona=story.get("persona", "user"),
            goal=story.get("goal", ""),
            benefit=story.get("benefit", ""),
            acceptance_criteria=acs,
            story_points=StoryPointValue(pts_val),
            priority=pri,
            title=story.get("title", ""),
            discipline=disc,
            points_rationale=story.get("rationale", ""),
        )

        w, h = console.size
        edited = edit_story(live, console, user_story, _rk, width=w, height=h)
        if edited is None:
            return None

        # Convert UserStory → dict (preserving extra keys from original)
        result = dict(story)
        result["title"] = edited.title
        result["persona"] = edited.persona
        result["goal"] = edited.goal
        result["benefit"] = edited.benefit
        result["story_points"] = int(edited.story_points)
        result["priority"] = edited.priority.value
        result["discipline"] = edited.discipline.value
        result["acceptance_criteria"] = [
            {"given": ac.given, "when": ac.when, "then": ac.then} for ac in edited.acceptance_criteria
        ]
        result["rationale"] = edited.points_rationale
        return result

    def _edit_task_dict(tasks_for_story: list[dict], story_id: str) -> list[dict] | None:
        """Edit tasks for a story using the planning mode task editor (with ANALYSIS title)."""
        from yeaboi.agent.state import Task
        from yeaboi.ui.session.editor._editor_artifacts import _find_first_editable, _task_editable_start
        from yeaboi.ui.session.editor._editor_core import edit_buffer_loop, render_editor_panel
        from yeaboi.ui.shared._components import analysis_title as _a_title

        task_objs = [
            Task(
                id=t.get("id", f"T-{story_id}-{i:02d}"),
                story_id=t.get("story_id", story_id),
                title=t.get("title", ""),
                description=t.get("description", ""),
                label=t.get("label", "Code"),
                test_plan=t.get("test_plan", ""),
            )
            for i, t in enumerate(tasks_for_story, 1)
        ]
        from yeaboi.ui.session.editor._editor_artifacts import _parse_edited_tasks, _tasks_to_text

        text = _tasks_to_text(task_objs)
        buffer = text.split("\n")
        cr, cc = _find_first_editable(buffer, _task_editable_start)
        _atitle = _a_title()

        def _render(buf, _cr, _cc, so, rw, rh):
            return render_editor_panel(
                buf,
                _cr,
                _cc,
                so,
                width=rw,
                height=rh,
                editor_label=f"tasks for {story_id}",
                title_override=_atitle,
            )

        result = edit_buffer_loop(
            live,
            console,
            buffer,
            cr,
            cc,
            _rk,
            editable_start_fn=_task_editable_start,
            render_fn=_render,
        )
        if result is None:
            return None
        edited_objs = _parse_edited_tasks("\n".join(result), task_objs)
        return [
            {**orig, "title": et.title, "description": et.description} for orig, et in zip(tasks_for_story, edited_objs)
        ]

    def _edit_epic_dict(epic: dict) -> dict | None:
        """Edit an epic dict using the planning mode feature editor (with ANALYSIS title)."""
        from yeaboi.agent.state import Feature, Priority
        from yeaboi.ui.session.editor._editor_artifacts import (
            _feature_editable_start,
            _features_to_text,
            _find_first_editable,
            _parse_edited_features,
        )
        from yeaboi.ui.session.editor._editor_core import edit_buffer_loop, render_editor_panel
        from yeaboi.ui.shared._components import analysis_title as _a_title

        pri_str = epic.get("priority", "high").lower()
        pri = Priority(pri_str) if pri_str in ("critical", "high", "medium", "low") else Priority.HIGH
        feature = Feature(
            id="F1",
            title=epic.get("title", ""),
            description=epic.get("description", ""),
            priority=pri,
        )
        text = _features_to_text([feature])
        buffer = text.split("\n")
        cr, cc = _find_first_editable(buffer, _feature_editable_start)
        _atitle = _a_title()

        def _render(buf, _cr, _cc, so, rw, rh):
            return render_editor_panel(
                buf,
                _cr,
                _cc,
                so,
                width=rw,
                height=rh,
                editor_label="epic",
                title_override=_atitle,
            )

        result = edit_buffer_loop(
            live,
            console,
            buffer,
            cr,
            cc,
            _rk,
            editable_start_fn=_feature_editable_start,
            render_fn=_render,
        )
        if result is None:
            return None
        edited_list = _parse_edited_features("\n".join(result), [feature])
        edited = edited_list[0]
        result_dict = dict(epic)
        result_dict["title"] = edited.title
        result_dict["description"] = edited.description
        result_dict["priority"] = edited.priority.value
        return result_dict

    def _regenerate(fn, label: str):
        """Run an LLM generation function in a background thread with animation."""
        import threading

        logger.info("Regenerating %s via LLM", label)

        result_box: list = [None, None]

        def _worker():
            try:
                result_box[0] = fn()
            except Exception as exc:
                result_box[1] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        start = time.monotonic()
        while thread.is_alive():
            elapsed = time.monotonic() - start
            w, h = console.size
            live.update(
                _build_analysis_progress_screen(
                    [f"Regenerating {label}\u2026"],
                    width=w,
                    height=h,
                    elapsed=elapsed,
                    anim_tick=elapsed,
                    source="",
                    mode="analysis",
                )
            )
            time.sleep(1 / 30)
        thread.join()
        if result_box[1] is not None:
            logger.warning("Regeneration failed: %s", result_box[1])
            return None
        logger.info("Regeneration complete: %s", label)
        return result_box[0]

    _flow_start = time.monotonic()
    last_page = (resume_state or {}).get("last_page", "")
    logger.info(
        "Preview flow started: resume=%s, last_page='%s'",
        resume_state is not None,
        last_page,
    )

    def _do_export():
        """Cumulative export — includes analysis profile + all accepted samples."""
        logger.info("Preview: exporting analysis (HTML + MD)")
        from yeaboi.agent.ceremony_history import gather_ceremony_context
        from yeaboi.team_profile_exporter import (
            export_team_profile_html,
            export_team_profile_md,
        )

        # Project-first here — the analysed project_key is known, so its retros sort ahead.
        ceremony = gather_ceremony_context(ta_profile.project_key)
        html_path = export_team_profile_html(ta_profile, examples=ta_examples, ceremony=ceremony)
        md_path = export_team_profile_md(ta_profile, examples=ta_examples, ceremony=ceremony)
        w, h = console.size
        from yeaboi.ui.mode_select.screens._screens_secondary import (
            _build_project_export_success_screen,
        )

        paths = f"HTML  {html_path}\nMD    {md_path}"
        live.update(
            _build_project_export_success_screen(
                paths,
                width=w,
                height=h,
                subtitle="Exported (HTML + MD)",
                mode="analysis",
            )
        )
        import time as _t

        _t0 = _t.monotonic()
        while True:
            _ek = _rk()
            if _t.monotonic() - _t0 > 1.5 and _ek:
                break

    # Ensure we have a session ID for saving progress
    global _ana_sid  # noqa: PLW0603
    if not _ana_sid:
        try:
            from yeaboi.sessions import SessionStore, make_session_id

            _ana_sid = make_session_id()
            with SessionStore(_ana_dbp) as _s:
                _s.create_session(
                    _ana_sid,
                    project_name=getattr(ta_profile, "project_key", "") if ta_profile else "",
                    mode="analysis",
                )
            logger.info("Created analysis session for preview: %s", _ana_sid)
        except Exception:
            logger.debug("Failed to create analysis session", exc_info=True)

    # Determine starting point and load saved artifacts
    last_page = (resume_state or {}).get("last_page", "")
    _instr = (resume_state or {}).get("instructions", "") or instr_text
    _epic = (resume_state or {}).get("sample_epic")
    _stories = (resume_state or {}).get("sample_stories")
    _tasks = (resume_state or {}).get("sample_tasks")
    _sprint = (resume_state or {}).get("sample_sprint")

    # Scroll geometry published by each page's screen builder; reused across the
    # sequential pages (repopulated on every render before any key is handled).
    _scroll_meta: dict = {}

    # ── Page 1: Instructions ──────────────────────────────────────
    logger.info("Preview: entering Instructions page")
    if last_page not in ("epic", "stories", "tasks", "sprint"):
        scroll, sel = 0, 0
        while True:
            k = _rk()
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(scroll, k, _scroll_meta, _rk)
                if _ns == scroll:
                    continue
                scroll = _ns
            elif k == "left":
                sel = max(0, sel - 1)
            elif k == "right":
                sel = min(2, sel + 1)
            elif k in ("enter", " "):
                if sel == 0:
                    _save_ana({"instructions": _instr, "last_page": "instructions"}, "instructions")
                    break  # → epic
                elif sel == 1:
                    # Edit — inline buffer editor (matches planning mode)
                    logger.info("Preview: user editing instructions")
                    from yeaboi.ui.session.editor._editor_core import edit_buffer_loop, render_editor_panel
                    from yeaboi.ui.shared._components import analysis_title as _a_title

                    _buf = _instr.split("\n")
                    _cr, _cc = 0, 0
                    _atitle = _a_title()

                    def _instr_render(buf, cr, cc, so, rw, rh):
                        return render_editor_panel(
                            buf,
                            cr,
                            cc,
                            so,
                            width=rw,
                            height=rh,
                            editor_label="instructions",
                            title_override=_atitle,
                        )

                    _edited = edit_buffer_loop(
                        live,
                        console,
                        _buf,
                        _cr,
                        _cc,
                        _rk,
                        editable_start_fn=lambda line: 0,
                        render_fn=_instr_render,
                    )
                    if _edited is not None:
                        _instr = "\n".join(_edited)
                elif sel == 2:
                    _do_export()
            elif k in ("esc", "q"):
                _save_ana({"instructions": _instr, "last_page": "instructions"}, "instructions")
                return
            w, h = console.size
            live.update(
                _build_instructions_review_screen(
                    _instr,
                    scroll_offset=scroll,
                    scroll_meta=_scroll_meta,
                    width=w,
                    height=h,
                    action_sel=sel,
                )
            )

    # ── Page 2: Epic ──────────────────────────────────────────────
    logger.info("Preview: entering Epic page")
    if not _epic:
        w, h = console.size
        live.update(
            _build_analysis_progress_screen(
                ["Generating sample epic\u2026"],
                width=w,
                height=h,
                elapsed=0,
                anim_tick=0,
                source="",
                mode="analysis",
            )
        )
        logger.info("Preview: generating sample epic via LLM")
        result = _regenerate(lambda: generate_sample_epic(_instr, ta_examples), "epic")
        if result is not None:
            _epic = result
        logger.info("Preview: sample epic generated: %s", _epic.get("title", "?"))
        # Persist the moment generation completes — not only on the Accept/next
        # keypress — so quitting here still leaves a resumable session (matches the
        # Accept-handler save dict below).
        _save_ana({"instructions": _instr, "sample_epic": _epic, "last_page": "epic"}, "epic")

    if last_page not in ("stories", "tasks", "sprint"):
        scroll, sel = 0, 0
        while True:
            k = _rk()
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(scroll, k, _scroll_meta, _rk)
                if _ns == scroll:
                    continue
                scroll = _ns
            elif k == "left":
                sel = max(0, sel - 1)
            elif k == "right":
                sel = min(3, sel + 1)
            elif k in ("enter", " "):
                if sel == 0:
                    _save_ana({"instructions": _instr, "sample_epic": _epic, "last_page": "epic"}, "epic")
                    break  # → stories
                elif sel == 1:
                    logger.info("Preview: user editing epic")
                    edited = _edit_epic_dict(_epic)
                    if edited is not None:
                        _epic = edited
                elif sel == 2:
                    # Ask what should change first (Esc cancels, empty Enter = plain regenerate).
                    fb = _ask_regen_feedback(console, live, read_key, frame_time, supports_timeout, "epic")
                    if fb is not None:
                        result = _regenerate(
                            lambda: generate_sample_epic(_instr, ta_examples, feedback=fb or None, previous=_epic),
                            "epic",
                        )
                        if result is not None:
                            _epic = result
                elif sel == 3:
                    _do_export()
            elif k in ("esc", "q"):
                _save_ana({"instructions": _instr, "sample_epic": _epic, "last_page": "epic"}, "epic")
                return
            w, h = console.size
            live.update(
                _build_sample_epic_screen(
                    _epic,
                    scroll_offset=scroll,
                    scroll_meta=_scroll_meta,
                    width=w,
                    height=h,
                    action_sel=sel,
                    examples=ta_examples,
                )
            )

    # ── Page 3: Stories ───────────────────────────────────────────
    logger.info("Preview: entering Stories page")
    if not _stories:
        w, h = console.size
        live.update(
            _build_analysis_progress_screen(
                ["Generating sample stories\u2026"],
                width=w,
                height=h,
                elapsed=0,
                anim_tick=0,
                source="",
                mode="analysis",
            )
        )
        logger.info("Preview: generating sample stories via LLM")
        result = _regenerate(lambda: generate_sample_stories(_instr, _epic, ta_examples), "stories")
        if result is not None:
            _stories = result
        logger.info("Preview: %d sample stories generated", len(_stories))
        # Persist on generation (see Epic page) so a mid-flow quit stays resumable.
        _save_ana(
            {
                "instructions": _instr,
                "sample_epic": _epic,
                "sample_stories": _stories,
                "last_page": "stories",
            },
            "stories",
        )

    if last_page not in ("tasks", "sprint"):
        scroll, sel = 0, 0
        while True:
            k = _rk()
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(scroll, k, _scroll_meta, _rk)
                if _ns == scroll:
                    continue
                scroll = _ns
            elif k == "left":
                sel = max(0, sel - 1)
            elif k == "right":
                sel = min(3, sel + 1)
            elif k in ("enter", " "):
                if sel == 0:
                    _st = {
                        "instructions": _instr,
                        "sample_epic": _epic,
                        "sample_stories": _stories,
                        "last_page": "stories",
                    }  # noqa: E501
                    _save_ana(_st, "stories")
                    break  # → tasks
                elif sel == 1:
                    logger.info("Preview: user editing stories")
                    for si, _s in enumerate(_stories):
                        edited = _edit_story_dict(_s)
                        if edited is not None:
                            _stories[si] = edited
                        else:
                            break  # Esc cancels remaining edits
                elif sel == 2:
                    fb = _ask_regen_feedback(console, live, read_key, frame_time, supports_timeout, "stories")
                    if fb is not None:
                        result = _regenerate(
                            lambda: generate_sample_stories(
                                _instr, _epic, ta_examples, feedback=fb or None, previous=_stories
                            ),
                            "stories",
                        )
                        if result is not None:
                            _stories = result
                elif sel == 3:
                    _do_export()
            elif k in ("esc", "q"):
                _save_ana(
                    {"instructions": _instr, "sample_epic": _epic, "sample_stories": _stories, "last_page": "stories"},
                    "stories",
                )
                return
            w, h = console.size
            live.update(
                _build_sample_stories_screen(
                    _stories,
                    scroll_offset=scroll,
                    scroll_meta=_scroll_meta,
                    width=w,
                    height=h,
                    action_sel=sel,
                    epic_title=_epic.get("title", ""),
                    examples=ta_examples,
                )
            )

    # ── Page 4: Tasks ─────────────────────────────────────────────
    logger.info("Preview: entering Tasks page")
    if not _tasks:
        w, h = console.size
        live.update(
            _build_analysis_progress_screen(
                ["Generating sample tasks\u2026"],
                width=w,
                height=h,
                elapsed=0,
                anim_tick=0,
                source="",
                mode="analysis",
            )
        )
        logger.info("Preview: generating sample tasks via LLM")
        result = _regenerate(lambda: generate_sample_tasks(_instr, _stories, ta_examples), "tasks")
        if result is not None:
            _tasks = result
        logger.info("Preview: %d sample tasks generated", len(_tasks))
        # Persist on generation (see Epic page) so a mid-flow quit stays resumable.
        _save_ana(
            {
                "instructions": _instr,
                "sample_epic": _epic,
                "sample_stories": _stories,
                "sample_tasks": _tasks,
                "last_page": "tasks",
            },
            "tasks",
        )

    if last_page != "sprint":
        scroll, sel = 0, 0
        while True:
            k = _rk()
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(scroll, k, _scroll_meta, _rk)
                if _ns == scroll:
                    continue
                scroll = _ns
            elif k == "left":
                sel = max(0, sel - 1)
            elif k == "right":
                sel = min(3, sel + 1)
            elif k in ("enter", " "):
                if sel == 0:
                    _st = {
                        "instructions": _instr,
                        "sample_epic": _epic,
                        "sample_stories": _stories,
                        "sample_tasks": _tasks,
                        "last_page": "tasks",
                    }  # noqa: E501
                    _save_ana(_st, "tasks")
                    break  # → sprint
                elif sel == 1:
                    logger.info("Preview: user editing tasks")
                    # Group tasks by story and edit each group
                    _by_story: dict[str, list[tuple[int, dict]]] = {}
                    for ti, _t in enumerate(_tasks):
                        sid = _t.get("story_id", "?")
                        _by_story.setdefault(sid, []).append((ti, _t))
                    _cancelled = False
                    for sid, group in _by_story.items():
                        group_tasks = [t for _, t in group]
                        edited_group = _edit_task_dict(group_tasks, sid)
                        if edited_group is None:
                            _cancelled = True
                            break
                        for (ti, _), et in zip(group, edited_group):
                            _tasks[ti] = et
                elif sel == 2:
                    fb = _ask_regen_feedback(console, live, read_key, frame_time, supports_timeout, "tasks")
                    if fb is not None:
                        result = _regenerate(
                            lambda: generate_sample_tasks(
                                _instr, _stories, ta_examples, feedback=fb or None, previous=_tasks
                            ),
                            "tasks",
                        )
                        if result is not None:
                            _tasks = result
                elif sel == 3:
                    _do_export()
            elif k in ("esc", "q"):
                _save_ana(
                    {
                        "instructions": _instr,
                        "sample_epic": _epic,
                        "sample_stories": _stories,
                        "sample_tasks": _tasks,
                        "last_page": "tasks",
                    },
                    "tasks",
                )
                return
            w, h = console.size
            live.update(
                _build_sample_tasks_screen(
                    _tasks,
                    scroll_offset=scroll,
                    scroll_meta=_scroll_meta,
                    width=w,
                    height=h,
                    action_sel=sel,
                    stories=_stories,
                )
            )

    # ── Page 5: Sprint ────────────────────────────────────────────
    logger.info(
        "Preview: entering Sprint page (%.1fs elapsed)",
        time.monotonic() - _flow_start,
    )
    _finished = _run_sprint_review(
        live,
        console,
        read_key,
        frame_time,
        supports_timeout,
        _instr,
        _epic,
        _stories,
        _tasks,
        ta_examples,
        resume_sprint=_sprint,
    )
    # Only mark the session complete (non-resumable) when the user actually
    # finished the Sprint page. On a quit, _run_sprint_review has already saved
    # the sprint with last_page="sprint", so the analysis resumes straight here.
    if _finished:
        _save_ana({"last_page": "complete"}, "complete")
    logger.info(
        "Preview flow completed in %.1fs",
        time.monotonic() - _flow_start,
    )


def _run_sprint_review(
    live,
    console,
    read_key,
    frame_time,
    supports_timeout,
    instr_text,
    sample_epic,
    sample_stories,
    sample_tasks,
    ta_examples,
    resume_sprint=None,
):
    """Run the sample sprint review loop (extracted to reduce nesting depth).

    Returns True if the user finished the page (chose "Done"), False if they quit
    (Esc). The caller uses this to decide whether to mark the session complete.
    """
    logger.info("Sprint review: generating sample sprint via LLM")
    import threading as _threading

    from yeaboi.tools.team_learning import generate_sample_sprint
    from yeaboi.ui.mode_select.screens._screens_secondary import (
        _build_analysis_progress_screen,
        _build_sample_sprint_screen,
    )

    def _save_sprint(sprint_obj: dict) -> None:
        # Persist the sprint the moment it is generated (see the Epic page), with
        # last_page="sprint" so a quit here resumes to this page without a re-run.
        _save_ana(
            {
                "instructions": instr_text,
                "sample_epic": sample_epic,
                "sample_stories": sample_stories,
                "sample_tasks": sample_tasks,
                "sample_sprint": sprint_obj,
                "last_page": "sprint",
            },
            "sprint",
        )

    def _regen_sprint(feedback=None, previous=None):
        result_box: list = [None, None]

        def _worker():
            try:
                result_box[0] = generate_sample_sprint(
                    instr_text, sample_stories, sample_tasks, ta_examples, feedback=feedback, previous=previous
                )
            except Exception as exc:
                result_box[1] = exc

        thread = _threading.Thread(target=_worker, daemon=True)
        thread.start()
        start = time.monotonic()
        while thread.is_alive():
            elapsed = time.monotonic() - start
            w, h = console.size
            live.update(
                _build_analysis_progress_screen(
                    ["Regenerating sprint\u2026"],
                    width=w,
                    height=h,
                    elapsed=elapsed,
                    anim_tick=elapsed,
                    source="",
                    mode="analysis",
                )
            )
            time.sleep(1 / 30)
        thread.join()
        if result_box[1] is not None:
            logger.warning("Sprint regeneration failed: %s", result_box[1])
            return None
        return result_box[0]

    if resume_sprint:
        # Resumed session — reuse the saved sprint, skip the (expensive) LLM call.
        sprint = resume_sprint
    else:
        sprint = _regen_sprint() or {
            "sprint_name": "Sprint 1",
            "velocity_target": 20,
            "stories_included": [s.get("id", "") for s in sample_stories],
            "total_points": sum(s.get("story_points", 0) for s in sample_stories),
            "capacity_notes": "Fallback — generation failed.",
            "risks": [],
            "rationale": "Fallback sprint plan.",
        }
        _save_sprint(sprint)
    scroll = 0
    sel = 0
    _scroll_meta: dict = {}
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if k in SCROLL_KEYS:
            _ns = coalesce_scroll(scroll, k, _scroll_meta, read_key)
            if _ns == scroll:
                continue
            scroll = _ns
        elif k == "left":
            sel = max(0, sel - 1)
        elif k == "right":
            sel = min(2, sel + 1)
        elif k in ("enter", " "):
            if sel == 0:
                return True  # Done — caller marks the session complete
            elif sel == 1:
                # Ask what should change first (Esc cancels, empty Enter = plain regenerate).
                fb = _ask_regen_feedback(console, live, read_key, frame_time, supports_timeout, "sprint")
                if fb is not None:
                    result = _regen_sprint(feedback=fb or None, previous=sprint)
                    if result is not None:
                        sprint = result
                        _save_sprint(sprint)
            elif sel == 2:
                pass  # Export (handled at report level)
        elif k in ("esc", "q"):
            return False  # Quit — keep last_page="sprint" so it stays resumable
        w, h = console.size
        live.update(
            _build_sample_sprint_screen(
                sprint,
                sample_stories,
                scroll_offset=scroll,
                scroll_meta=_scroll_meta,
                width=w,
                height=h,
                action_sel=sel,
            )
        )


def _collect_usage_data() -> dict:
    """Gather usage statistics for the Usage dashboard page."""
    import os
    import sys

    data: dict = {}

    # Provider info
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    model = os.environ.get("LLM_MODEL", "")
    if not model:
        _defaults = {
            "anthropic": "claude-sonnet-4-6",
            "openai": "gpt-4o",
            "google": "gemini-2.5-flash",
            "bedrock": "us.anthropic.claude-sonnet-4-6-v1:0",
        }
        model = _defaults.get(provider, "unknown")
    data["provider"] = provider
    data["model"] = model

    # API key status
    _key_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "bedrock": "AWS_REGION",
    }
    key_var = _key_vars.get(provider, "ANTHROPIC_API_KEY")
    data["api_key_status"] = "configured" if os.environ.get(key_var) else "not configured"

    # Session history
    try:
        from yeaboi.sessions import SessionStore

        db_path = _ana_dbp
        with SessionStore(db_path) as store:
            all_sessions = store.list_sessions()
            analysis_sessions = store.list_analysis_sessions()
            planning_count = len(all_sessions) - len(analysis_sessions)
            last_used = all_sessions[0].get("last_modified", "") if all_sessions else ""
            data["sessions"] = {
                "total": len(all_sessions),
                "planning": planning_count,
                "analysis": len(analysis_sessions),
                "last_used": last_used[:19].replace("T", " ") if last_used else "",
            }
    except Exception:
        data["sessions"] = {"total": 0, "planning": 0, "analysis": 0}

    # Environment
    from yeaboi import __version__

    data["version"] = __version__
    data["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    from yeaboi.config import is_langsmith_enabled

    data["langsmith"] = "enabled" if is_langsmith_enabled() else "disabled"
    data["db_path"] = str(_ana_dbp)

    # Team profiles
    try:
        from yeaboi.team_profile import TeamProfileStore

        with TeamProfileStore(_ana_dbp) as ps:
            profiles = ps.list_profiles()
            data["profiles"] = [
                {
                    "name": getattr(p, "team_id", "?"),
                    "source": getattr(p, "source", "?"),
                    "sprints": getattr(p, "sample_sprints", 0),
                }
                for p in profiles
            ]
    except Exception:
        data["profiles"] = []

    # Token usage — session (in-memory) + lifetime (from DB)
    def _calc_cost(inp: int, out: int) -> float:
        # Claude Sonnet 4: $3/MTok input, $15/MTok output
        return round((inp * 3.0 + out * 15.0) / 1_000_000, 4)

    try:
        from yeaboi.agent.llm import get_usage_stats

        stats = get_usage_stats()
        logger.info("Usage stats: %s", stats)
        if stats.get("call_count", 0) > 0:
            inp = stats.get("input_tokens", 0)
            out = stats.get("output_tokens", 0)
            data["tokens"] = {
                "input": inp,
                "output": out,
                "total": inp + out,
                "calls": stats.get("call_count", 0),
                "estimated_cost": _calc_cost(inp, out),
            }
        else:
            data["tokens"] = {}
    except Exception:
        data["tokens"] = {}

    # Lifetime usage from DB (persisted across all sessions)
    try:
        from yeaboi.sessions import SessionStore

        with SessionStore(_ana_dbp) as store:
            lifetime = store.get_lifetime_usage()
            if lifetime.get("call_count", 0) > 0:
                lt_inp = lifetime["input_tokens"]
                lt_out = lifetime["output_tokens"]
                data["lifetime_tokens"] = {
                    "input": lt_inp,
                    "output": lt_out,
                    "total": lt_inp + lt_out,
                    "calls": lifetime["call_count"],
                    "estimated_cost": _calc_cost(lt_inp, lt_out),
                }
            else:
                data["lifetime_tokens"] = {}
    except Exception:
        data["lifetime_tokens"] = {}

    return data


def _collect_settings_data() -> dict:
    """Gather current configuration values for the Settings page."""
    import os

    from yeaboi.config import get_config_file

    data: dict[str, str] = {}
    # Read all known env vars
    _keys = [
        "LLM_PROVIDER",
        "LLM_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "JIRA_BASE_URL",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "JIRA_PROJECT_KEY",
        "CONFLUENCE_SPACE_KEY",
        "AZURE_DEVOPS_ORG_URL",
        "AZURE_DEVOPS_PROJECT",
        "AZURE_DEVOPS_TOKEN",
        "AZURE_DEVOPS_TEAM",
        "GITHUB_TOKEN",
        "VOICE_MODEL",
        "AWS_REGION",
        "AWS_PROFILE",
        "LOG_LEVEL",
        "SESSION_PRUNE_DAYS",
        "LANGSMITH_TRACING",
        "TIPS_ENABLED",
        # Daily Standup delivery config (secrets masked by the settings screen)
        "STANDUP_GITHUB_REPO",
        "SLACK_WEBHOOK_URL",
        "STANDUP_SMTP_HOST",
        "STANDUP_SMTP_USER",
        "STANDUP_SMTP_PASSWORD",
        "STANDUP_EMAIL_RECIPIENTS",
    ]
    for k in _keys:
        data[k] = os.environ.get(k, "")
    data["_config_path"] = str(get_config_file())
    return data


def _collect_standup_data(message: str = "") -> dict:
    """Gather Daily Standup dashboard data for the most recent session.

    The standup page targets the most recently modified session. Returns the
    session name, saved standup config, OS-schedule status, and the latest
    generated StandupReport (if any).
    """
    from yeaboi.config import get_standup_user_name

    data: dict = {
        "message": message,
        "session_id": "",
        "session_name": "",
        "my_name": get_standup_user_name(),
        "config": None,
        "report": None,
        "schedule": {},
    }
    try:
        from yeaboi.sessions import SessionStore, make_display_name

        with SessionStore(_ana_dbp) as store:
            session_id = store.get_latest_session_id()
            if not session_id:
                return data
            data["session_id"] = session_id
            meta = store.get_session(session_id) or {}
            data["session_name"] = make_display_name(meta) if meta else session_id
    except Exception:
        logger.warning("standup: failed to resolve latest session", exc_info=True)
        return data

    session_id = data["session_id"]
    try:
        from yeaboi.standup.store import StandupStore

        with StandupStore(_ana_dbp) as store:
            data["config"] = store.load_config(session_id)
            data["report"] = store.get_latest_report(session_id)
        # The engine resolves "Me" to the user's real tracker identity (e.g. their
        # Jira displayName) — the report's my_name drives the "My Update" row.
        if data["report"] is not None and data["report"].my_name:
            data["my_name"] = data["report"].my_name
    except Exception:
        logger.warning("standup: failed to load standup store data", exc_info=True)
    try:
        from yeaboi.standup.scheduler import get_schedule_status

        data["schedule"] = get_schedule_status(session_id)
    except Exception:
        logger.warning("standup: failed to read schedule status", exc_info=True)
    return data


def _standup_generate(session_id: str, on_progress=None) -> str:
    """Run a standup for preview (no delivery) and return a status message."""
    try:
        from yeaboi.standup.engine import run_standup

        report = run_standup(session_id, deliver=False, dry_run=True, on_progress=on_progress)
        warn = f" · {len(report.warnings)} notice(s)" if report.warnings else ""
        logger.info(
            "standup: generated report — day %s/%s, %d notice(s) (session=%s)",
            report.sprint_day,
            report.sprint_total_days,
            len(report.warnings),
            session_id,
        )
        return f"Generated — day {report.sprint_day}/{report.sprint_total_days}, {report.confidence_label}{warn}."
    except Exception as e:
        logger.error("standup: generate failed: %s", e, exc_info=True)
        return f"Generate failed: {e}"


def _standup_export(session_id: str, data: dict) -> str:
    """Export the latest standup report as Markdown + HTML. Returns a status message."""
    from yeaboi.standup.export import export_standup
    from yeaboi.standup.store import StandupStore

    with StandupStore(_ana_dbp) as store:
        report = store.get_latest_report(session_id)
    if report is None:
        logger.info("standup export: nothing to export yet (session=%s)", session_id)
        return "Nothing to export yet — press Generate first."
    try:
        paths = export_standup(report, project_name=data.get("session_name", "") or session_id)
        logger.info("standup export: wrote Markdown + HTML to %s (session=%s)", paths["markdown"].parent, session_id)
        return f"Exported to {paths['markdown'].parent}  (Markdown + HTML)"
    except Exception as e:
        logger.error("standup export failed: %s", e, exc_info=True)
        return f"Export failed: {e}"


def _standup_generate_flow(
    console: Console, live, read_key, frame_time, supports_timeout, session_id: str
) -> str | None:
    """Ask the user for their own update, save it, then generate the standup.

    Returns a status message on success, or None if the user pressed Esc at the
    update prompt (cancel — no run). Pressing Enter with an empty update skips the
    self-report and generates with inference.
    """
    from datetime import date

    from yeaboi.config import get_standup_user_name
    from yeaboi.standup.store import StandupStore
    from yeaboi.ui.shared._attachments import referenced_images

    attachments: list[str] = []
    update = _standup_read_line(
        console,
        live,
        read_key,
        frame_time,
        supports_timeout,
        prompt="Your update for today (Enter to skip)",
        step="Generate standup  —  add your update",
        default="",
        box_rows=6,
        attachments=attachments,
        scope_id=session_id or "standup",
    )
    if update is None:
        logger.info("standup generate: cancelled at update prompt (session=%s)", session_id)
        return None  # Esc → cancel the whole Generate
    if update.strip():
        member = get_standup_user_name()
        with StandupStore(_ana_dbp) as store:
            store.save_my_update(
                session_id,
                date.today().isoformat(),
                member,
                update.strip(),
                images=referenced_images(update, attachments),
            )
        logger.info("standup generate: self-update saved (session=%s)", session_id)

    # Run the pipeline on a worker thread while the frame loop shows live
    # progress — collection + the LLM call can take many seconds, and without
    # this the input box just sat frozen (same pattern as the analysis pages).
    import threading

    from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_progress_screen

    progress: list[str] = ["Starting"]
    result_box: list = [None]

    def _worker() -> None:
        result_box[0] = _standup_generate(session_id, on_progress=progress.append)

    thread = threading.Thread(target=_worker, name="standup-generate", daemon=True)
    thread.start()
    start = time.monotonic()
    while thread.is_alive():
        elapsed = time.monotonic() - start
        w, h = console.size
        live.update(
            _build_standup_progress_screen(
                list(progress),
                width=w,
                height=max(10, h - 1),
                elapsed=elapsed,
                anim_tick=elapsed,
            )
        )
        time.sleep(1 / 30)
    thread.join()
    return result_box[0]


def _ask_regen_feedback(console: Console, live, read_key, frame_time, supports_timeout, label: str) -> str | None:
    """Prompt for feedback before regenerating a sample artifact.

    Returns the feedback text, "" when the user just pressed Enter (regenerate
    as-is, same prompt as today), or None when they pressed Esc (cancel the
    regenerate entirely — no LLM call).
    """
    from yeaboi.ui.shared._components import ANALYSIS_THEME, analysis_title

    fb = _standup_read_line(
        console,
        live,
        read_key,
        frame_time,
        supports_timeout,
        prompt="What should change? (Enter to regenerate as-is)",
        step=f"Regenerate {label} — feedback",
        default="",
        theme=ANALYSIS_THEME,
        title=analysis_title(),
        box_rows=6,
    )
    if fb is None:
        logger.info("Regenerate %s: cancelled at feedback prompt", label)
    elif fb:
        logger.info("Regenerate %s: feedback given (%d chars)", label, len(fb))
    else:
        logger.info("Regenerate %s: no feedback, regenerating as-is", label)
    return fb


def _standup_read_line(
    console: Console,
    live,
    read_key,
    frame_time: float,
    supports_timeout: bool,
    *,
    prompt: str,
    step: str,
    default: str = "",
    theme=None,
    title=None,
    box_rows: int = 1,
    attachments: list[str] | None = None,
    scope_id: str = "",
) -> str | None:
    """Collect a single line of input inside the Live display (themed, read_key-driven).

    Returns the typed value (or the default on empty Enter), or None if the user
    pressed Esc to cancel. Because it uses read_key — which consumes mouse events
    and returns printable chars — there's no raw terminal prompt and no mouse-escape
    leakage.

    Voice dictation (double-tap Space) works here just like the artifact editors:
    the transcript is inserted at the cursor and the recording indicator renders
    inline on this same screen.

    ``theme``/``title`` re-brand the screen for non-standup pages (e.g. the
    analysis regenerate-feedback prompt); defaults keep the standup look.

    attachments: caller-owned list that Ctrl+V screenshot paths are appended to
        (each marked by an [image #N] chip in the text; resolve survivors with
        referenced_images() after submit). None disables image paste — Ctrl+V
        shows the standard "not supported" notice instead.
    """
    import time as _time

    from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_input_screen
    from yeaboi.ui.shared._attachments import handle_ctrl_v, unsupported_notice
    from yeaboi.ui.shared._voice_input import DoubleTapSpace, record_voice_input, voice_indicator

    value = ""
    notice = ""
    _dts = DoubleTapSpace()

    def _set_notice(msg: str) -> None:
        nonlocal notice
        notice = msg

    def _render(*, border_style: str = "", status: str = "") -> None:
        w, h = console.size
        live.update(
            _build_standup_input_screen(
                prompt,
                value,
                step=step,
                default=default,
                width=w,
                height=max(10, h - 1),
                border_style=border_style,
                status=status,
                theme=theme,
                title=title,
                box_rows=box_rows,
                show_image_hint=attachments is not None,
            )
        )

    # Voice overlay re-renders THIS screen (not a popup) with the pulsing
    # indicator. record_voice_input() calls this and does the live.update itself,
    # so we only return the renderable.
    def _render_status(status_name: str, tick: float):
        w, h = console.size
        border, line = voice_indicator(status_name, tick)
        return _build_standup_input_screen(
            prompt,
            value,
            step=step,
            default=default,
            width=w,
            height=max(10, h - 1),
            border_style=border,
            status=line,
            theme=theme,
            title=title,
            box_rows=box_rows,
        )

    _render()
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if k and k != "":
            notice = ""
        if k == "enter":
            return value.strip() or default
        if k == "esc":
            return None
        if k == "alt+enter":
            # Alt+Enter / Ctrl+N inserts a newline — only meaningful in the large
            # multi-row box; the single-row field keeps ignoring it.
            if box_rows > 1:
                value += "\n"
        elif k == "backspace":
            value = value[:-1]
        elif k == "clear":  # Ctrl+U
            value = ""
        elif k == "word_backspace":  # Ctrl+W
            value = value.rstrip().rsplit(" ", 1)[0] if " " in value.strip() else ""
        elif isinstance(k, str) and k.startswith("paste:"):
            value += k[len("paste:") :]
        elif k == "ctrl+v":
            if attachments is None:
                unsupported_notice(_set_notice)
            else:
                _render(status="Pasting image…")
                chip = handle_ctrl_v(attachments, scope_id=scope_id or "standup", set_notice=_set_notice)
                if chip:
                    value += chip
                    notice = f"Screenshot attached as {chip}"
        elif k == " " and _dts.is_double(value.endswith(" "), _time.monotonic()):
            # Double-tap Space → dictate. The first space (already in `value`)
            # stays as a separator; the transcript is appended after it.
            spoken = record_voice_input(live, console, read_key, _render_status)
            if spoken:
                value += spoken.replace("\n", " ")
        elif isinstance(k, str) and len(k) == 1 and k.isprintable():
            value += k
        _render(status=notice)


def _standup_configure(console: Console, live, read_key, frame_time, supports_timeout, session_id: str) -> str:
    """Collect schedule/delivery settings in-TUI, persist them, and (un)install the OS schedule.

    Each field defaults to the existing config (Enter keeps it). Esc at any field
    cancels the whole flow. Returns a status message for the dashboard.
    """
    from yeaboi.standup.delivery import ALL_CHANNELS
    from yeaboi.standup.scheduler import install_schedule, remove_schedule
    from yeaboi.standup.store import StandupStore

    with StandupStore(_ana_dbp) as store:
        existing = store.load_config(session_id) or {}
    cur_time = existing.get("time", "10:00")
    cur_lead = str(existing.get("lead_minutes", 10))
    cur_days = existing.get("weekdays", "1-5")
    cur_channels = ", ".join(existing.get("delivery_channels", ["terminal"]))
    cur_repo = existing.get("repo_path", "")
    cur_aliases = existing.get("my_aliases", "")
    cur_enabled = "yes" if existing.get("enabled") else "no"

    def _ask(prompt: str, step: str, default: str) -> str | None:
        value = _standup_read_line(
            console, live, read_key, frame_time, supports_timeout, prompt=prompt, step=step, default=default
        )
        if value is None:
            logger.info("standup configure: cancelled at %s (session=%s)", step.strip(), session_id)
        return value

    # Ask for the STANDUP time (when it happens); the job fires a few minutes before.
    time_in = _ask("Standup time (HH:MM) — the meeting time", "Configure standup  (1/7)", cur_time)
    if time_in is None:
        return "Configure cancelled."
    lead_in = _ask("Run how many minutes before the standup?", "Configure standup  (2/7)", cur_lead)
    if lead_in is None:
        return "Configure cancelled."
    days_in = _ask("Weekdays (e.g. 1-5 or 1,3,5)", "Configure standup  (3/7)", cur_days)
    if days_in is None:
        return "Configure cancelled."
    channels_in = _ask("Delivery channels (terminal, desktop, slack, email)", "Configure standup  (4/7)", cur_channels)
    if channels_in is None:
        return "Configure cancelled."
    repo_in = _ask("Local git repo path (optional)", "Configure standup  (5/7)", cur_repo)
    if repo_in is None:
        return "Configure cancelled."
    # Aliases let your activity (GitHub handle, Jira display name, commit email)
    # attach to YOUR standup card even when the names don't match exactly.
    aliases_in = _ask(
        "Your aliases across tools (comma-separated, e.g. GitHub handle, Jira name)",
        "Configure standup  (6/7)",
        cur_aliases,
    )
    if aliases_in is None:
        return "Configure cancelled."
    enable_in = _ask("Enable scheduled runs? (yes/no)", "Configure standup  (7/7)", cur_enabled)
    if enable_in is None:
        return "Configure cancelled."

    enabled = enable_in.strip().lower() in ("y", "yes", "true", "on", "1")
    channels = [c.strip() for c in channels_in.split(",") if c.strip() in ALL_CHANNELS] or ["terminal"]
    try:
        lead_minutes = max(0, int(lead_in))
    except ValueError:
        lead_minutes = 10

    with StandupStore(_ana_dbp) as store:
        store.save_config(
            session_id,
            enabled=enabled,
            time=time_in,
            lead_minutes=lead_minutes,
            weekdays=days_in,
            delivery_channels=channels,
            repo_path=repo_in,
            my_aliases=aliases_in.strip(),
        )

    msg = install_schedule(session_id, time_in, days_in, lead_minutes) if enabled else remove_schedule(session_id)
    logger.info("standup configure: session=%s enabled=%s -> %s", session_id, enabled, msg)
    return msg


def _run_changelog_page(console: Console, live, read_key, frame_time: float, supports_timeout: bool) -> None:
    """Event loop for the Changelog page (opened with `c` from mode select).

    Read-only: Up/Down scrolls the release notes, Enter/Esc/q returns to mode
    select. Data is the bundled ``changelog_data.json`` (no network); the upgrade
    banner reflects whatever the background PyPI check has found so far.
    """
    from yeaboi.changelog import load_changelog
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_changelog_screen
    from yeaboi.update_check import get_update_status

    entries = load_changelog()
    update_status = get_update_status()
    logger.info(
        "changelog: page opened (%d entries, update_available=%s)", len(entries), update_status["update_available"]
    )
    scroll = 0
    _scroll_meta: dict = {}
    anim_start = time.monotonic()  # shimmer title + typewriter subtitle clock

    def _render() -> None:
        w, h = console.size
        elapsed = time.monotonic() - anim_start
        # One-row safety margin — same as the other pages (see _run_standup_page).
        live.update(
            _build_changelog_screen(
                entries,
                update_status=update_status,
                scroll_offset=scroll,
                scroll_meta=_scroll_meta,
                width=w,
                height=max(10, h - 1),
                action_sel=0,
                shimmer_tick=elapsed,
                sub_reveal=elapsed * _HEADER_SUB_SPEED,
            )
        )

    _render()
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if k in SCROLL_KEYS:
            _ns = coalesce_scroll(scroll, k, _scroll_meta, read_key)
            if _ns == scroll:
                continue
            scroll = _ns
        elif k in ("enter", " ", "esc", "q"):  # single Back button
            break
        _render()
    logger.info("changelog: page closed")


def _run_standup_page(console: Console, live, read_key, frame_time: float, supports_timeout: bool) -> None:
    """Event loop for the Daily Standup page (overview + expandable sections).

    Follows the team-analysis pattern: the overview lists selectable section
    cards (Team Summary, Sprint & Confidence, My Update, Team, Activity,
    Schedule, Notices) with a two-zone focus model: Up/Down focuses the list
    and moves the selection, Enter opens the selected section directly —
    except the Team row, where Enter toggles the inline member sub-rows;
    Left/Right moves focus to the button row (Generate / Configure / Back),
    where Enter presses the highlighted button. A detail view free-scrolls
    with Up/Down; Back/Esc returns to the overview. Generate/Configure open
    themed in-TUI input screens (driven by read_key, so no raw prompt and no
    mouse-escape leakage), then refresh. Generate collects the user's own
    update first, so there is no separate My Update button.
    """
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_screen
    from yeaboi.ui.mode_select.screens._standup_sections import standup_card_order

    team_expanded = False  # inline Team-row expansion; survives data refreshes
    data = _collect_standup_data()
    data["team_expanded"] = team_expanded
    view = "overview"
    focus = "sections"  # overview focus zone: "sections" | "buttons"
    card_idx, scroll, sel = 0, 0, 0
    _scroll_meta: dict = {}
    anim_start = time.monotonic()  # shimmer title + typewriter subtitle clock

    def _actions() -> list[str]:
        return ["Generate", "Configure", "Back"] if view == "overview" else ["Back", "Export"]

    def _open_section() -> None:
        nonlocal view, scroll, sel, team_expanded
        order = standup_card_order(data)
        if not order:
            return
        key = order[card_idx % len(order)]
        if key == "team":  # Team row toggles its inline sub-rows, no detail view
            team_expanded = not team_expanded
            data["team_expanded"] = team_expanded
            logger.info("standup: team row %s", "expanded" if team_expanded else "collapsed")
            return
        view = key
        scroll = 0
        sel = 0
        logger.info("standup: opened section %s", view)

    def _reset_to_overview() -> None:
        nonlocal view, scroll, sel, card_idx, focus
        view = "overview"
        focus = "sections"
        scroll = 0
        sel = 0
        # Refreshes rebuild the data dict, so re-apply the expansion flag here
        # (every refresh is followed by this reset).
        data["team_expanded"] = team_expanded
        card_idx = min(card_idx, max(0, len(standup_card_order(data)) - 1))

    def _render() -> None:
        w, h = console.size
        elapsed = time.monotonic() - anim_start
        # Leave a one-row safety margin: a Live renderable exactly equal to the
        # terminal height loses its last row (the action buttons) to the cursor.
        live.update(
            _build_standup_screen(
                data,
                scroll_offset=scroll,
                scroll_meta=_scroll_meta,
                width=w,
                height=max(10, h - 1),
                # No button is highlighted while the section list has focus.
                action_sel=-1 if (view == "overview" and focus == "sections") else sel,
                shimmer_tick=elapsed,
                sub_reveal=elapsed * _HEADER_SUB_SPEED,
                view=view,
                selected_card=card_idx,
                actions=_actions(),
            )
        )

    _render()
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if view == "overview" and k in SCROLL_KEYS:
            # On the overview, Up/Down focuses the section list and moves the
            # selection (the screen auto-scrolls the selected row into view).
            focus = "sections"
            order = standup_card_order(data)
            if order:
                card_idx += 1 if k in ("down", "scroll_down", "pagedown") else -1
                card_idx %= len(order)
        elif k in SCROLL_KEYS:
            _ns = coalesce_scroll(scroll, k, _scroll_meta, read_key)
            if _ns == scroll:
                continue
            scroll = _ns
        elif k == "left":
            if view == "overview" and focus != "buttons":
                focus = "buttons"  # first Left/Right only moves focus to the row
            else:
                sel = max(0, sel - 1)
        elif k == "right":
            if view == "overview" and focus != "buttons":
                focus = "buttons"
            else:
                sel = min(len(_actions()) - 1, sel + 1)
        elif k in ("enter", " "):
            session_id = data.get("session_id", "")
            if not session_id:
                logger.info("standup: no session available — returning to mode select")
                break
            if view == "overview" and focus == "sections":
                _open_section()
                _render()
                continue
            act = _actions()[sel]
            if act == "Back":
                if view == "overview":
                    break
                _reset_to_overview()
            elif act == "Generate":  # ask for the user's own update first, then run
                logger.info("standup: Generate pressed (session=%s)", session_id)
                try:
                    proceed = _standup_generate_flow(console, live, read_key, frame_time, supports_timeout, session_id)
                except Exception as e:  # never let a prompt crash the TUI
                    logger.error("standup generate failed: %s", e, exc_info=True)
                    proceed = f"Generate failed: {e}"
                data = _collect_standup_data(message=proceed if proceed is not None else "")
                _reset_to_overview()
            elif act == "Export":  # write the latest report as Markdown + HTML
                logger.info("standup: Export pressed (session=%s)", session_id)
                data = _collect_standup_data(message=_standup_export(session_id, data))
                _reset_to_overview()
            else:  # Configure — in-TUI themed input (stays inside Live)
                try:
                    logger.info("standup: Configure pressed (session=%s)", session_id)
                    msg = _standup_configure(console, live, read_key, frame_time, supports_timeout, session_id)
                except Exception as e:  # never let a prompt crash the TUI
                    logger.error("standup action failed: %s", e, exc_info=True)
                    msg = f"Action failed: {e}"
                data = _collect_standup_data(message=msg)
                _reset_to_overview()
        elif k in ("esc", "q"):
            if view == "overview":
                break
            _reset_to_overview()
        _render()
    logger.info("standup: page closed (session=%s)", data.get("session_id", ""))


# ---------------------------------------------------------------------------
# Performance mode page
# ---------------------------------------------------------------------------


def _collect_performance_data(message: str = "") -> dict:
    """Gather Performance page data: latest session + the Jira/AzDO engineer roster.

    The roster is the real people who did work on the board (assignees) — see
    performance/roster.py. Session context (sprint length/project) is best-effort;
    the page still works with no session.
    """
    data: dict = {"message": message, "session_id": "", "session_name": "", "roster": [], "roster_hints": []}
    try:
        from yeaboi.sessions import SessionStore, make_display_name

        with SessionStore(_ana_dbp) as store:
            session_id = store.get_latest_session_id() or ""
            data["session_id"] = session_id
            if session_id:
                meta = store.get_session(session_id) or {}
                data["session_name"] = make_display_name(meta) if meta else session_id
    except Exception:
        logger.warning("performance: failed to resolve latest session", exc_info=True)
    try:
        from yeaboi.performance.roster import fetch_roster

        data["roster"] = [r.name for r in fetch_roster()]
    except Exception:
        logger.warning("performance: failed to fetch roster", exc_info=True)
    # Fallback: no live Jira/AzDO roster → use the planning session's own team
    # members (also board-derived) so Performance is usable without a live tracker.
    if not data["roster"] and data["session_id"]:
        data["roster"] = _performance_session_team(data["session_id"])
        if data["roster"]:
            logger.info("performance: roster fell back to session team members")
    data["roster_hints"] = _performance_roster_hints(data["roster"])
    logger.info("performance: %d engineer(s) in roster", len(data["roster"]))
    return data


def _performance_session_team(session_id: str) -> list[str]:
    """Return the session's team-member names (fallback roster when no tracker).

    Reads ``selected_team_members`` from the saved plan state — the same
    board-derived roster the standup uses. Best-effort: any error → []. Names are
    de-duplicated preserving order and sorted for a stable page.
    """
    try:
        from yeaboi.sessions import SessionStore

        with SessionStore(_ana_dbp) as store:
            state = store.load_state(session_id) or {}
    except Exception:
        logger.warning("performance: failed to load session team members", exc_info=True)
        return []
    names = [str(n).strip() for n in (state.get("selected_team_members") or ()) if str(n).strip()]
    return sorted(dict.fromkeys(names), key=str.lower)


def _performance_roster_hints(roster: list[str]) -> list[str]:
    """Build a one-line status hint per engineer (open 1:1 actions + review on file).

    Shown as the description under the selected engineer's big ASCII name. Best-effort
    — a store error just yields the generic hint so the page always renders.
    """
    generic = "1:1 prep · completion · 6-month review"
    if not roster:
        return []
    try:
        from yeaboi.performance.store import PerformanceStore

        with PerformanceStore(_ana_dbp) as store:
            open_actions = store.get_all_open_action_items()
            hints: list[str] = []
            for name in roster:
                n = len(open_actions.get(name, ()))
                has_review = store.get_latest_review(name) is not None
                if n:
                    hint = f"{n} open 1:1 action{'s' if n != 1 else ''}"
                else:
                    hint = "no open 1:1 actions"
                if has_review:
                    hint += " · review on file"
                hints.append(hint)
            return hints
    except Exception:
        logger.warning("performance: failed to build roster hints", exc_info=True)
        return [generic for _ in roster]


def _performance_get_transcript(console, live, read_key, frame_time, supports_timeout) -> tuple[str, list[str]] | None:
    """Collect a 1:1 transcript — via a file path, or pasted/typed inline.

    Returns (transcript_text, image_paths), or None if the user cancelled (Esc).
    Supports both input methods per the design: a file path is read from disk; an
    empty path drops to an inline paste field. In the inline field, Ctrl+V attaches
    screenshots (e.g. a photo of whiteboard notes) that the summarising LLM call
    receives as multimodal image blocks.
    """
    path = _standup_read_line(
        console,
        live,
        read_key,
        frame_time,
        supports_timeout,
        prompt="Transcript file path (Enter to paste instead)",
        step="1:1 Complete  —  transcript source",
        default="",
    )
    if path is None:
        return None
    path = path.strip()
    if path:
        try:
            from pathlib import Path

            text = Path(path).expanduser().read_text(encoding="utf-8")
            logger.info("performance: read transcript from %s (%d chars)", path, len(text))
            return text, []
        except Exception as e:  # noqa: BLE001 — fall through to paste on a bad path
            logger.warning("performance: could not read transcript file %s: %s", path, e)

    from yeaboi.ui.shared._attachments import referenced_images

    attachments: list[str] = []
    text = _standup_read_line(
        console,
        live,
        read_key,
        frame_time,
        supports_timeout,
        prompt="Paste the meeting notes / transcript",
        step="1:1 Complete  —  paste transcript",
        default="",
        attachments=attachments,
        scope_id="performance",
    )
    if text is None:
        return None
    return text, referenced_images(text, attachments)


def _performance_export(engineer: str) -> str:
    """Re-export the engineer's most recent artifact (review > completion > prep)."""
    from yeaboi.performance import export
    from yeaboi.performance.store import PerformanceStore

    with PerformanceStore(_ana_dbp) as store:
        review = store.get_latest_review(engineer)
        completions = store.get_recent_completions(engineer, limit=1)
        prep = store.get_latest_prep(engineer)
    artifact, kind = None, ""
    if review is not None:
        artifact, kind = review, "review"
    elif completions:
        artifact, kind = completions[0], "completion"
    elif prep is not None:
        artifact, kind = prep, "prep"
    if artifact is None:
        logger.info("performance export: nothing to export yet for engineer=%s", engineer)
        return "Nothing to export yet — generate a 1:1 prep or review first."
    try:
        paths = export.export_artifact(artifact, engineer=engineer, kind=kind)
        logger.info("performance export: wrote %s for engineer=%s to %s", kind, engineer, paths["markdown"].parent)
        return f"Exported {kind} to {paths['markdown'].parent}  (Markdown + HTML)"
    except Exception as e:  # noqa: BLE001
        logger.error("performance export failed: %s", e, exc_info=True)
        return f"Export failed: {e}"


def _run_team_analysis_results(
    live,
    console: Console,
    read_key,
    frame_time: float,
    supports_timeout: bool,
    profile,
    examples: dict | None,
    *,
    sprint_names: list[str] | None = None,
    team_name: str = "",
) -> str:
    """Event loop for the team-analysis results screen (overview + section cards).

    Starts on the overview (headline stats, AI executive summary, section list):
    Up/Down choose a section card, Enter on "Open" shows that card's detail view
    (metrics + AI "What this means" + glossary), Back/Esc returns to the
    overview. Export writes HTML + MD from any view. Returns ``"continue"``
    when the user chose Continue (ticket generation) and ``"back"`` on Esc from
    the overview — the callers own what happens next.
    """
    from yeaboi.ui.mode_select.screens._analysis_sections import _TA_CARD_ORDER

    view = "overview"
    card_idx = 0
    scroll = 0
    scroll_meta: dict = {}
    sel = 0
    anim0 = time.monotonic()  # shimmer title clock
    logger.info("Analysis results: showing overview for %s/%s", profile.source, profile.project_key)

    while True:
        actions = ["Open", "Export", "Continue"] if view == "overview" else ["Back", "Export", "Continue"]

        w, h = console.size
        live.update(
            _build_team_analysis_screen(
                profile,
                scroll_offset=scroll,
                scroll_meta=scroll_meta,
                width=w,
                height=h,
                export_sel=sel,
                examples=examples,
                sprint_names=sprint_names,
                team_name=team_name,
                view=view,
                selected_card=card_idx,
                actions=actions,
                shimmer_tick=time.monotonic() - anim0,
            )
        )

        kk = read_key(timeout=frame_time) if supports_timeout else read_key()
        if view == "overview" and kk in SCROLL_KEYS:
            # On the overview, Up/Down moves the card selection (the screen
            # auto-scrolls the selected row into view).
            card_idx += 1 if kk in ("down", "scroll_down", "pagedown") else -1
            card_idx %= len(_TA_CARD_ORDER)
        elif kk in SCROLL_KEYS:
            scroll = coalesce_scroll(scroll, kk, scroll_meta, read_key)
        elif kk == "left":
            sel = max(0, sel - 1)
        elif kk == "right":
            sel = min(len(actions) - 1, sel + 1)
        elif kk in ("enter", " "):
            act = actions[sel]
            if act == "Open":
                view = _TA_CARD_ORDER[card_idx]
                scroll = 0
                sel = 0
                logger.info("Analysis results: opened section %s", view)
            elif act == "Back":
                view = "overview"
                scroll = 0
                sel = 0
            elif act == "Export":
                from yeaboi.team_profile_exporter import (
                    export_team_profile_html,
                    export_team_profile_md,
                )

                export_team_profile_html(profile, examples=examples, sprint_names=sprint_names)
                exp_path = export_team_profile_md(profile, examples=examples, sprint_names=sprint_names)
                logger.info("Analysis results: exported profile to %s", exp_path)
                w, h = console.size
                live.update(
                    _build_project_export_success_screen(
                        str(exp_path),
                        width=w,
                        height=h,
                        subtitle="Team profile exported",
                        mode="analysis",
                    )
                )
                exp_t0 = time.monotonic()
                while True:
                    ek = read_key(timeout=frame_time) if supports_timeout else read_key()
                    if time.monotonic() - exp_t0 > 1.5 and ek:
                        break
            elif act == "Continue":
                logger.info("Analysis results: continue to ticket generation")
                return "continue"
        elif kk in ("esc", "q"):
            if view == "overview":
                logger.info("Analysis results: closed")
                return "back"
            view = "overview"
            scroll = 0
            sel = 0


def _run_performance_page(console: Console, live, read_key, frame_time: float, supports_timeout: bool) -> None:
    """Event loop for the Performance page.

    Two views. In "roster": Up/Down choose an engineer, Left/Right pick an action
    (1:1 Prep / 1:1 Complete / 6mo Review / Notes / Export / Back), Enter runs it —
    an AI action switches to "detail" showing the artifact. In "detail": Up/Down
    scroll, Export re-writes the artifact, Back returns to the roster.

    # See README: "Performance Mode" — TUI page
    """
    from yeaboi.performance.render import (
        format_completion_lines,
        format_prep_lines,
        format_review_lines,
    )
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_performance_screen

    base = _collect_performance_data()
    session_id = base["session_id"]
    session_name = base["session_name"]
    roster: list[str] = base["roster"]
    roster_hints: list[str] = base.get("roster_hints", [])

    state = {
        "view": "roster",
        "selected": 0,
        "scroll": 0,
        "scroll_meta": {},
        "sel": 0,
        "message": "",
        "detail_lines": [],
        "detail_title": "",
    }
    roster_actions = ["1:1 Prep", "1:1 Complete", "6mo Review", "Notes", "Export", "Back"]
    detail_actions = ["Export", "Back"]

    def _data() -> dict:
        return {
            "session_name": session_name,
            "view": state["view"],
            "roster": roster,
            "roster_hints": roster_hints,
            "selected_idx": state["selected"],
            "detail_lines": state["detail_lines"],
            "detail_title": state["detail_title"],
            "actions": roster_actions if state["view"] == "roster" else detail_actions,
            "message": state["message"],
        }

    # Animation clocks — mirror the intake mode picker: a shimmer sweeps the
    # selected engineer's ASCII name (shimmer_tick) and its description reveals
    # typewriter-style (desc_reveal), reset whenever the selection changes.
    anim_start = time.monotonic()
    state["select_time"] = anim_start

    def _render() -> None:
        w, h = console.size
        now = time.monotonic()
        tick = now - anim_start  # title shimmer (+ roster-word shimmer) — runs in both views
        sub_reveal = tick * _HEADER_SUB_SPEED
        # The per-engineer description only reveals in the roster view, and restarts
        # whenever the selection changes (select_time), like the intake picker.
        reveal = (now - state["select_time"]) * _DESC_SCROLL_SPEED if state["view"] == "roster" else 0.0
        live.update(
            _build_performance_screen(
                _data(),
                scroll_offset=state["scroll"],
                scroll_meta=state["scroll_meta"],
                width=w,
                height=max(10, h - 1),
                action_sel=state["sel"],
                shimmer_tick=tick,
                desc_reveal=reveal,
                sub_reveal=sub_reveal,
            )
        )

    def _show_detail(lines: list[str], title: str, message: str) -> None:
        state["view"] = "detail"
        state["detail_lines"] = lines
        state["detail_title"] = title
        state["message"] = message
        state["sel"] = 0
        state["scroll"] = 0

    def _run_action(label: str, engineer: str) -> None:
        """Run one AI/notes action for the selected engineer (blocks briefly)."""
        try:
            if label == "1:1 Prep":
                from yeaboi.performance.engine import run_one_on_one_prep

                prep = run_one_on_one_prep(engineer, session_id=session_id, db_path=_ana_dbp)
                logger.info("performance: 1:1 prep generated for engineer=%s", engineer)
                _show_detail(format_prep_lines(prep), f"1:1 Prep — {engineer}", "Prep generated.")
            elif label == "1:1 Complete":
                transcript_result = _performance_get_transcript(console, live, read_key, frame_time, supports_timeout)
                if transcript_result is None or not transcript_result[0].strip():
                    logger.info("performance: 1:1 completion cancelled — no transcript (engineer=%s)", engineer)
                    state["message"] = "1:1 completion cancelled — no transcript."
                    return
                transcript, transcript_images = transcript_result
                from yeaboi.performance.engine import complete_one_on_one

                record = complete_one_on_one(
                    engineer, transcript, session_id=session_id, db_path=_ana_dbp, images=transcript_images
                )
                sent = "email sent" if not record.warnings else "see notices"
                logger.info("performance: 1:1 completed for engineer=%s (%s)", engineer, sent)
                _show_detail(format_completion_lines(record), f"1:1 Summary — {engineer}", f"Completed — {sent}.")
            elif label == "6mo Review":
                from yeaboi.performance.engine import run_six_month_review

                review = run_six_month_review(engineer, session_id=session_id, db_path=_ana_dbp)
                logger.info("performance: 6-month review generated for engineer=%s", engineer)
                _show_detail(format_review_lines(review), f"6-Month Review — {engineer}", "Review generated.")
            elif label == "Notes":
                note = _standup_read_line(
                    console,
                    live,
                    read_key,
                    frame_time,
                    supports_timeout,
                    prompt=f"Note about {engineer}",
                    step="Performance  —  add note",
                    default="",
                )
                if note and note.strip():
                    from yeaboi.performance.store import PerformanceStore

                    with PerformanceStore(_ana_dbp) as store:
                        store.add_note(engineer, note.strip())
                    logger.info("performance: note saved for engineer=%s", engineer)
                    state["message"] = f"Note saved for {engineer}."
                else:
                    logger.info("performance: note cancelled — nothing entered (engineer=%s)", engineer)
                    state["message"] = "No note entered."
        except Exception as e:  # never let an action crash the TUI
            logger.error("performance action %s failed: %s", label, e, exc_info=True)
            state["message"] = f"{label} failed: {e}"

    _render()
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if state["view"] == "roster":
            if k in ("up", "scroll_up"):
                if roster:
                    state["selected"] = (state["selected"] - 1) % len(roster)
                    state["select_time"] = time.monotonic()  # restart the description reveal
            elif k in ("down", "scroll_down"):
                if roster:
                    state["selected"] = (state["selected"] + 1) % len(roster)
                    state["select_time"] = time.monotonic()
            elif k == "left":
                state["sel"] = max(0, state["sel"] - 1)
            elif k == "right":
                state["sel"] = min(len(roster_actions) - 1, state["sel"] + 1)
            elif k in ("enter", " "):
                label = roster_actions[state["sel"]]
                if label == "Back":
                    break
                if not roster:
                    logger.info("performance: %s pressed with empty roster", label)
                    state["message"] = "No engineers — connect Jira or Azure DevOps first."
                else:
                    engineer = roster[state["selected"]]
                    logger.info("performance: %s pressed for engineer=%s", label, engineer)
                    if label == "Export":
                        state["message"] = _performance_export(engineer)
                    else:
                        _run_action(label, engineer)
                        # An action may have changed open-action counts / added a
                        # review — refresh the per-engineer hints shown in the roster.
                        roster_hints[:] = _performance_roster_hints(roster)
            elif k in ("esc", "q"):
                break
        else:  # detail view
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(state["scroll"], k, state["scroll_meta"], read_key)
                if _ns == state["scroll"]:
                    continue  # at a boundary — don't repaint (avoids title-shimmer flicker)
                state["scroll"] = _ns
            elif k == "left":
                state["sel"] = max(0, state["sel"] - 1)
            elif k == "right":
                state["sel"] = min(len(detail_actions) - 1, state["sel"] + 1)
            elif k in ("enter", " "):
                label = detail_actions[state["sel"]]
                if label == "Back":
                    state["view"] = "roster"
                    state["sel"], state["scroll"], state["message"] = 0, 0, ""
                    state["select_time"] = time.monotonic()  # replay the reveal on return
                elif label == "Export" and roster:
                    logger.info("performance: Export pressed in detail view for engineer=%s", roster[state["selected"]])
                    state["message"] = _performance_export(roster[state["selected"]])
            elif k in ("esc", "q"):
                state["view"] = "roster"
                state["sel"], state["scroll"], state["message"] = 0, 0, ""
                state["select_time"] = time.monotonic()
        _render()
    logger.info("performance: page closed (session=%s)", session_id)


def _collect_reporting_data(message: str = "") -> dict:
    """Gather Reporting page data: the latest session id + display name.

    The report itself is generated on demand (Generate button); this just resolves
    which session's sprint length / project name the report should use. Best-effort —
    the page still works with no session (it reports from the live tracker config).
    """
    data: dict = {"message": message, "session_id": "", "session_name": ""}
    try:
        from yeaboi.sessions import SessionStore, make_display_name

        with SessionStore(_ana_dbp) as store:
            session_id = store.get_latest_session_id() or ""
            data["session_id"] = session_id
            if session_id:
                meta = store.get_session(session_id) or {}
                data["session_name"] = make_display_name(meta) if meta else session_id
    except Exception:
        logger.warning("reporting: failed to resolve latest session", exc_info=True)
    logger.info("reporting: session=%s", data["session_id"])
    return data


def _run_reporting_page(console: Console, live, read_key, frame_time: float, supports_timeout: bool) -> None:
    """Event loop for the Reporting page.

    Three views. In "picker": Up/Down choose a period (Last sprint / Last month /
    Whole quarter), Left/Right pick an action (Generate Report / Theme / Back). For a
    quarter, Generate opens "sprint_select": Up/Down move, Space toggles which sprints
    make up the quarter (the current quarter's sprints pre-checked), Enter generates.
    "detail" shows the report: Up/Down scroll, Export re-writes files, Theme cycles the
    slide-deck palette, Back returns to the picker.

    # See README: "Reporting Mode" — TUI page
    """
    from datetime import date as _date

    from yeaboi.reporting.activity import (
        PERIOD_LABELS,
        PERIOD_LAST_MONTH,
        PERIOD_LAST_SPRINT,
        PERIOD_QUARTER,
    )
    from yeaboi.reporting.presentation import THEMES
    from yeaboi.reporting.render import format_report_lines
    from yeaboi.reporting.sprints import list_sprints, mark_in_quarter, quarter_bounds
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_reporting_screen

    base = _collect_reporting_data()
    session_id = base["session_id"]
    session_name = base["session_name"]

    q_label, q_start, q_end = quarter_bounds()
    periods = [
        (PERIOD_LAST_SPRINT, PERIOD_LABELS[PERIOD_LAST_SPRINT], "The most recent sprint's completed work"),
        (PERIOD_LAST_MONTH, PERIOD_LABELS[PERIOD_LAST_MONTH], "The last ~4 weeks across ~2 sprints"),
        (PERIOD_QUARTER, f"Whole quarter ({q_label})", "Pick the sprints that make up the quarter"),
    ]

    state = {
        "view": "picker",
        "selected": 0,  # period index
        "scroll": 0,
        "scroll_meta": {},
        "sel": 0,  # action button index
        "message": "",
        "theme": "midnight",
        "detail_lines": [],
        "detail_title": "",
        "report": None,
        # sprint_select view state
        "sprints": [],  # list[SprintRef]
        "sprint_cursor": 0,
        "sprint_checked": set(),
    }
    picker_actions = ["Generate Report", "Theme", "Back"]
    detail_actions = ["Export", "Theme", "Back"]
    sprint_actions = ["Generate Report", "Back"]

    def _actions() -> list[str]:
        if state["view"] == "detail":
            return detail_actions
        if state["view"] == "sprint_select":
            return sprint_actions
        return picker_actions

    def _data() -> dict:
        return {
            "session_name": session_name,
            "view": state["view"],
            "periods": periods,
            "selected_idx": state["selected"],
            "theme": state["theme"],
            "detail_lines": state["detail_lines"],
            "detail_title": state["detail_title"],
            "actions": _actions(),
            "message": state["message"],
            # sprint_select rendering
            "quarter_label": q_label,
            "sprints": state["sprints"],
            "sprint_cursor": state["sprint_cursor"],
            "sprint_checked": state["sprint_checked"],
        }

    anim_start = time.monotonic()

    def _render() -> None:
        w, h = console.size
        tick = time.monotonic() - anim_start
        live.update(
            _build_reporting_screen(
                _data(),
                scroll_offset=state["scroll"],
                scroll_meta=state["scroll_meta"],
                width=w,
                height=max(10, h - 1),
                action_sel=state["sel"],
                shimmer_tick=tick,
                sub_reveal=tick * _HEADER_SUB_SPEED,
            )
        )

    def _show_report(report, msg: str) -> None:
        state["report"] = report
        state["detail_lines"] = format_report_lines(report)
        state["detail_title"] = f"Delivery Report — {report.period_label}"
        state["view"] = "detail"
        state["sel"], state["scroll"] = 0, 0
        state["message"] = msg

    def _delivered_msg(report) -> str:
        n = len(report.delivered_items)
        plural = "s" if n != 1 else ""
        return f"Report generated — {n} item{plural} delivered. Auto-saved (md/html/slides)."

    def _generate() -> None:
        """Generate the delivery report for the selected non-quarter period."""
        period_key = periods[state["selected"]][0]
        logger.info("reporting: generating report (period=%s, session=%s)", period_key, session_id)
        try:
            from yeaboi.reporting.engine import run_delivery_report

            report = run_delivery_report(period_key, session_id=session_id, db_path=_ana_dbp)
            logger.info("reporting: report generated — %d item(s) (period=%s)", len(report.delivered_items), period_key)
            _show_report(report, _delivered_msg(report))
        except Exception as e:  # never let an action crash the TUI
            logger.error("reporting generate failed: %s", e, exc_info=True)
            state["message"] = f"Generate failed: {e}"

    def _run_quarter(window_start: str, window_end: str, names: tuple, label: str) -> None:
        """Generate a quarter report over an explicit sprint-derived window."""
        logger.info(
            "reporting: generating quarter report %s → %s over %d sprint(s) (session=%s)",
            window_start,
            window_end,
            len(names),
            session_id,
        )
        try:
            from yeaboi.reporting.engine import run_delivery_report

            report = run_delivery_report(
                PERIOD_QUARTER,
                session_id=session_id,
                db_path=_ana_dbp,
                window_start=window_start,
                window_end=window_end,
                sprint_names=names,
                period_label_override=label,
            )
            logger.info("reporting: quarter report generated — %d item(s)", len(report.delivered_items))
            _show_report(report, _delivered_msg(report))
        except Exception as e:  # never let an action crash the TUI
            logger.error("reporting quarter generate failed: %s", e, exc_info=True)
            state["message"] = f"Generate failed: {e}"

    def _open_sprint_select() -> None:
        """Load the sprint list for the quarter and switch to the multi-select view.

        When no sprint list is available (no tracker, no plan sprints), skip the
        picker and report straight over the calendar-quarter dates.
        """
        plan_state = {}
        try:
            from yeaboi.sessions import SessionStore

            with SessionStore(_ana_dbp) as store:
                plan_state = store.load_state(session_id) or {}
        except Exception:  # noqa: BLE001 — plan state is only the fallback source
            logger.warning("reporting: could not load plan state for sprint list", exc_info=True)
        refs = mark_in_quarter(list_sprints(plan_state), q_start, q_end)
        if not refs:
            logger.info("reporting: no sprint list available — reporting over the calendar quarter")
            today_iso = _date.today().isoformat()
            _run_quarter(q_start, min(q_end, today_iso), (), q_label)
            state["message"] = "No sprint list available — reported over the calendar quarter. " + state["message"]
            return
        logger.info("reporting: sprint multi-select opened (%d sprint(s))", len(refs))
        state["sprints"] = refs
        state["sprint_checked"] = {i for i, s in enumerate(refs) if s.in_quarter}
        inq = [i for i, s in enumerate(refs) if s.in_quarter]
        state["sprint_cursor"] = inq[0] if inq else 0
        state["view"] = "sprint_select"
        state["sel"], state["scroll"], state["message"] = 0, 0, ""

    def _generate_from_selection() -> None:
        """Compute the window from the checked sprints and generate the quarter report."""
        refs = state["sprints"]
        checked = sorted(i for i in state["sprint_checked"] if 0 <= i < len(refs))
        if not checked:
            logger.info("reporting: sprint selection confirmed with no sprints checked")
            state["message"] = "Select at least one sprint (Space to toggle)."
            return
        logger.info("reporting: sprint selection confirmed (%d of %d sprint(s))", len(checked), len(refs))
        sel = [refs[i] for i in checked]
        starts = [s.start_date for s in sel if s.start_date]
        ends = [s.end_date for s in sel if s.end_date]
        today_iso = _date.today().isoformat()
        window_start = min(starts) if starts else q_start
        window_end = min(max(ends) if ends else q_end, today_iso)
        names = tuple(s.name for s in sel)
        detected = {i for i, s in enumerate(refs) if s.in_quarter}
        label = q_label if set(checked) == detected else f"{q_label} (custom)"
        _run_quarter(window_start, window_end, names, label)

    def _export() -> None:
        report = state.get("report")
        if report is None:
            logger.info("reporting: Export pressed with nothing to export")
            state["message"] = "Nothing to export yet — generate a report first."
            return
        logger.info("reporting: Export pressed (period=%s)", report.period_label)
        try:
            from yeaboi.reporting.export import export_report

            paths = export_report(report, theme=state["theme"])
            logger.info("reporting: exported to %s (theme=%s)", paths["markdown"].parent, state["theme"])
            state["message"] = f"Exported to {paths['markdown'].parent}  (Markdown + HTML + slides)"
        except Exception as e:  # noqa: BLE001
            logger.error("reporting export failed: %s", e, exc_info=True)
            state["message"] = f"Export failed: {e}"

    def _cycle_theme() -> None:
        idx = (list(THEMES).index(state["theme"]) + 1) % len(THEMES) if state["theme"] in THEMES else 0
        state["theme"] = THEMES[idx]
        logger.info("reporting: presentation theme cycled to %s", state["theme"])
        state["message"] = f"Presentation theme: {state['theme']}"

    _render()
    while True:
        k = read_key(timeout=frame_time) if supports_timeout else read_key()
        if state["view"] == "picker":
            if k in ("up", "scroll_up"):
                state["selected"] = (state["selected"] - 1) % len(periods)
            elif k in ("down", "scroll_down"):
                state["selected"] = (state["selected"] + 1) % len(periods)
            elif k == "left":
                state["sel"] = max(0, state["sel"] - 1)
            elif k == "right":
                state["sel"] = min(len(picker_actions) - 1, state["sel"] + 1)
            elif k in ("enter", " "):
                label = picker_actions[state["sel"]]
                if label == "Back":
                    break
                elif label == "Generate Report":
                    if periods[state["selected"]][0] == PERIOD_QUARTER:
                        _open_sprint_select()
                    else:
                        _generate()
                elif label == "Theme":
                    _cycle_theme()
            elif k in ("esc", "q"):
                break
        elif state["view"] == "sprint_select":
            n_sprints = len(state["sprints"])
            if k in ("up", "scroll_up"):
                if n_sprints:
                    state["sprint_cursor"] = (state["sprint_cursor"] - 1) % n_sprints
            elif k in ("down", "scroll_down"):
                if n_sprints:
                    state["sprint_cursor"] = (state["sprint_cursor"] + 1) % n_sprints
            elif k == " ":  # toggle the sprint under the cursor
                cur = state["sprint_cursor"]
                if cur in state["sprint_checked"]:
                    state["sprint_checked"].discard(cur)
                else:
                    state["sprint_checked"].add(cur)
            elif k == "left":
                state["sel"] = max(0, state["sel"] - 1)
            elif k == "right":
                state["sel"] = min(len(sprint_actions) - 1, state["sel"] + 1)
            elif k == "enter":
                label = sprint_actions[state["sel"]]
                if label == "Back":
                    state["view"] = "picker"
                    state["sel"], state["scroll"], state["message"] = 0, 0, ""
                else:  # Generate Report
                    _generate_from_selection()
            elif k in ("esc", "q"):
                state["view"] = "picker"
                state["sel"], state["scroll"], state["message"] = 0, 0, ""
        else:  # detail view
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(state["scroll"], k, state["scroll_meta"], read_key)
                if _ns == state["scroll"]:
                    continue  # at a boundary — don't repaint (avoids title-shimmer flicker)
                state["scroll"] = _ns
            elif k == "left":
                state["sel"] = max(0, state["sel"] - 1)
            elif k == "right":
                state["sel"] = min(len(detail_actions) - 1, state["sel"] + 1)
            elif k in ("enter", " "):
                label = detail_actions[state["sel"]]
                if label == "Back":
                    state["view"] = "picker"
                    state["sel"], state["scroll"], state["message"] = 0, 0, ""
                elif label == "Export":
                    _export()
                elif label == "Theme":
                    _cycle_theme()
            elif k in ("esc", "q"):
                state["view"] = "picker"
                state["sel"], state["scroll"], state["message"] = 0, 0, ""
        _render()
    logger.info("reporting: page closed (session=%s)", session_id)


def _resolve_retro_session() -> tuple[str, str, str, str]:
    """Resolve the retro's target session → (session_id, session_name, project_name, sprint_name).

    Like the standup page, the retro targets the most recently modified session.
    Returns empty strings when there is no session yet.
    """
    try:
        from yeaboi.sessions import SessionStore, make_display_name

        with SessionStore(_ana_dbp) as store:
            session_id = store.get_latest_session_id()
            if not session_id:
                return "", "", "", ""
            meta = store.get_session(session_id) or {}
            state = store.load_state(session_id) or {}
        session_name = make_display_name(meta) if meta else session_id
        project_name = state.get("project_name", "") or session_name
        # Sprint name is best-effort: the export/report titles degrade gracefully if blank.
        sprint_name = str(state.get("sprint_name", "") or "")
        return session_id, session_name, project_name, sprint_name
    except Exception:
        logger.warning("retro: failed to resolve latest session", exc_info=True)
        return "", "", "", ""


def _run_retro_page(console: Console, live, read_key, frame_time: float, supports_timeout: bool) -> None:
    """Event loop for the collaborative Retro board page.

    Starts a small LAN web server so teammates can add cards from a browser; the
    board refreshes every frame as cards arrive — the existing frame-timed
    read_key loop IS the live-update mechanism, so no extra TUI-side thread is
    needed (the only background thread is the HTTP server itself). Buttons:
    [Generate Action Items, Export, Close]. Up/Down scroll, Left/Right select,
    Enter activates. On exit the board is flushed to RetroStore and the server is
    torn down (in a finally, so Ctrl-C/exception still persists + stops it).

    # See README: "Retro" — TUI page, LAN collaboration
    """
    from yeaboi.ui.mode_select.screens._screens_secondary import _build_retro_screen

    anim_start = time.monotonic()  # shimmer title + typewriter subtitle clock
    _scroll_meta: dict = {}  # scroll geometry published by _build_retro_screen

    def _render(data: dict, scroll: int, sel: int) -> None:
        w, h = console.size
        elapsed = time.monotonic() - anim_start
        # Leave a one-row safety margin (same reason as the standup page).
        live.update(
            _build_retro_screen(
                data,
                scroll_offset=scroll,
                scroll_meta=_scroll_meta,
                width=w,
                height=max(10, h - 1),
                action_sel=sel,
                shimmer_tick=elapsed,
                sub_reveal=elapsed * _HEADER_SUB_SPEED,
            )
        )

    session_id, session_name, project_name, sprint_name = _resolve_retro_session()
    if not session_id:
        logger.info("retro: no session available — showing notice")
        data = {
            "session_name": "",
            "display_code": "—",
            "url": "—",
            "message": "No project session yet — create one in Planning first, then start a retro.",
            "grids": {},
        }
        _render(data, 0, 2)
        while True:
            k = read_key(timeout=frame_time) if supports_timeout else read_key()
            if k in ("enter", " ", "esc", "q"):
                break
            _render(data, 0, 2)
        return

    from yeaboi.config import get_retro_server_port
    from yeaboi.retro.board import RetroBoard, board_to_report
    from yeaboi.retro.server import RetroServer
    from yeaboi.retro.store import RetroStore

    board = RetroBoard(session_id, project_name=project_name, sprint_name=sprint_name)
    server = RetroServer(board, port=get_retro_server_port())
    try:
        server.start()
        logger.info("retro: server started on port %s (session=%s)", server.port, session_id)
    except OSError as e:
        logger.error("retro: failed to start server: %s", e, exc_info=True)
        data = {
            "session_name": session_name,
            "display_code": "—",
            "url": "—",
            "message": f"Could not start the retro server: {e}",
            "grids": {},
        }
        _render(data, 0, 2)
        while True:
            k = read_key(timeout=frame_time) if supports_timeout else read_key()
            if k in ("enter", " ", "esc", "q"):
                break
            _render(data, 0, 2)
        return

    logger.info("retro: page opened for session=%s on %s", session_id, server.url.split("?")[0])
    scroll, sel = 0, 0
    message = "Server ready — share the code below so teammates can add cards from their browser."

    # Remote tunnel state. Setup (binary download + tunnel handshake) is slow, so
    # it runs on a worker thread; the frame-timed loop shows its progress and the
    # public URL as soon as it's ready. `active`/`starting` drive the button label.
    import threading as _threading

    remote: dict = {"tunnel": None, "url": "", "status": "", "active": False, "starting": False}

    def _start_remote() -> None:
        def _worker() -> None:
            try:
                from yeaboi.retro.tunnel import CloudflareTunnel, ensure_cloudflared

                remote["status"] = "Setting up remote link — fetching cloudflared (first use, ~40MB)…"
                binary = ensure_cloudflared()
                if binary is None:
                    logger.warning("retro: remote link failed — could not obtain cloudflared binary")
                    remote["status"] = "Remote link failed — could not obtain cloudflared (see logs)."
                    return
                remote["status"] = "Starting secure Cloudflare tunnel…"
                tunnel = CloudflareTunnel(server.port, binary=binary)
                public = tunnel.start(timeout=30)
                if not public:
                    tunnel.stop()
                    logger.warning("retro: remote link failed — tunnel did not start within timeout")
                    remote["status"] = "Remote link failed — tunnel did not start (see logs)."
                    return
                logger.info("retro: remote tunnel ready (port=%s)", server.port)
                remote["tunnel"] = tunnel
                # Token-free public URL: off-network teammates must still enter the
                # join code (the token is never handed out in a shareable link).
                remote["url"] = f"{public}/"
                remote["active"] = True
                remote["status"] = "Remote link ready — share the Remote URL with off-network teammates."
            except Exception as e:  # never let the worker crash anything
                logger.error("retro: remote tunnel setup failed: %s", e, exc_info=True)
                remote["status"] = f"Remote link failed — {e}"
            finally:
                remote["starting"] = False

        logger.info("retro: Share Remotely pressed — starting tunnel setup (session=%s)", session_id)
        remote["starting"] = True
        remote["status"] = "Setting up remote link…"
        _threading.Thread(target=_worker, name="retro-tunnel-setup", daemon=True).start()

    def _stop_remote() -> None:
        logger.info("retro: Stop Sharing pressed — stopping remote tunnel (session=%s)", session_id)
        tunnel = remote.get("tunnel")
        if tunnel is not None:
            tunnel.stop()
        remote.update({"tunnel": None, "url": "", "active": False, "starting": False})
        remote["status"] = "Remote link stopped — LAN sharing still on."

    def _share_label() -> str:
        if remote["active"]:
            return "Stop Sharing"
        if remote["starting"]:
            return "Sharing…"
        return "Share Remotely"

    def _actions() -> list[str]:
        # Buttons: 0 Generate, 1 Share/Stop, 2 Export, 3 Close.
        return ["Generate Action Items", _share_label(), "Export", "Close"]

    def _data() -> dict:
        return {
            "session_name": session_name,
            "display_code": server.display_code,
            "url": server.share_url,
            "host_url": server.url,
            "public_url": remote["url"],
            "message": remote["status"] or message,
            "grids": board.cards_by_grid(),
            "actions": _actions(),
        }

    n_buttons = 4  # Generate Action Items, Share Remotely, Export, Close

    try:
        _render(_data(), scroll, sel)
        while True:
            k = read_key(timeout=frame_time) if supports_timeout else read_key()
            if k in SCROLL_KEYS:
                _ns = coalesce_scroll(scroll, k, _scroll_meta, read_key)
                if _ns == scroll:
                    continue
                scroll = _ns
            elif k == "left":
                sel = max(0, sel - 1)
            elif k == "right":
                sel = min(n_buttons - 1, sel + 1)
            elif k in ("enter", " "):
                if sel == 3:  # Close
                    break
                if sel == 0:  # Generate Action Items (one LLM call, never raises)
                    logger.info("retro: Generate Action Items pressed (session=%s)", session_id)
                    try:
                        from yeaboi.retro.engine import generate_action_items

                        message = generate_action_items(board)
                        logger.info("retro: generate action items result: %s", message)
                    except Exception as e:  # defensive — never let it crash the TUI
                        logger.error("retro: generate action items failed: %s", e, exc_info=True)
                        message = f"Generate failed: {e}"
                    scroll = 0
                elif sel == 1:  # Share Remotely / Stop Sharing (public Cloudflare tunnel)
                    if remote["active"]:
                        _stop_remote()
                    elif not remote["starting"]:
                        _start_remote()
                    scroll = 0
                elif sel == 2:  # Export → Markdown + HTML
                    logger.info("retro: Export pressed (session=%s)", session_id)
                    try:
                        from yeaboi.retro.export import export_retro

                        report = board_to_report(board, sprint_name=sprint_name)
                        paths = export_retro(report, project_name=project_name or session_name)
                        logger.info("retro: exported to %s", paths["markdown"].parent)
                        message = f"Exported to {paths['markdown'].parent}  (Markdown + HTML)"
                    except Exception as e:
                        logger.error("retro: export failed: %s", e, exc_info=True)
                        message = f"Export failed: {e}"
                    scroll = 0
            elif k in ("esc", "q"):
                break
            _render(_data(), scroll, sel)
    finally:
        # Always flush the board, stop the tunnel, and tear the server down — even
        # on exception or Ctrl-C — so the retro persists and no process leaks.
        try:
            report = board_to_report(board, sprint_name=sprint_name)
            with RetroStore(_ana_dbp) as store:
                store.record_run(report)
        except Exception as e:
            logger.warning("retro: flush to store failed: %s", e)
        if remote.get("tunnel") is not None:
            remote["tunnel"].stop()
        server.stop()
        logger.info("retro: page closed for session=%s", session_id)


def select_mode(
    console: Console | None = None, *, dry_run: bool = False, _read_key_fn=None
) -> tuple[str, str | None, str | None] | None:
    """Show full-screen mode selection, then project list → intake mode for Planning.

    Returns (mode_key, intake_mode, questionnaire_path) tuple or None if cancelled.
    - Small:  ("project-planning", "small_project", None)
    - Epic:   ("project-planning", "smart", None)
    - Import: ("project-planning", None, "/path/to/questionnaire.md")
    - Export/Cancel: None
    Only available modes can be selected.
    """
    console = console or Console()
    read_key = _read_key_fn or _read_key
    selected = 0
    n = len(_MODE_CARDS)

    # Kick off the one-shot PyPI update check on a daemon thread. Idempotent and
    # fire-and-forget — the bottom-left version row picks the result up whenever
    # a frame renders after the fetch lands.
    from yeaboi.update_check import start_background_check

    start_background_check()

    w, h = console.size
    start_time = time.monotonic()
    select_time = start_time

    import inspect

    _supports_timeout = "timeout" in inspect.signature(read_key).parameters

    all_mode_indices = list(range(n))

    # If alt-screen is already active (from splash), use screen=False so
    # Live doesn't toggle it (which causes a visible flicker).  If not
    # active, let Live manage it normally with screen=True.
    _screen_managed_by_live = not console.is_alt_screen

    with make_live(
        _build_mode_screen(
            selected,
            width=w,
            height=h,
            shimmer_tick=0.0,
            desc_reveal=0,
            fade_style=FADE_IN_LEVELS[0],
            fade_indices=all_mode_indices,
        ),
        console=console,
        refresh_per_second=60,
        screen=_screen_managed_by_live,
    ) as live:
        # Outer loop: returns here when user presses Esc from project list
        # to go back to mode selection (instead of recursive select_mode call).
        _restart_mode_select = True
        _skip_fade_in = False
        while _restart_mode_select:
            _restart_mode_select = False

            if _skip_fade_in:
                # Esc transition already rendered all items — no fade needed.
                # Description typewriter starts fresh from now.
                _skip_fade_in = False
            else:
                # Fade in all three mode items from near-black to full colour
                for grey in FADE_IN_LEVELS:
                    w, h = console.size
                    live.update(
                        _build_mode_screen(
                            selected,
                            width=w,
                            height=h,
                            shimmer_tick=0.0,
                            desc_reveal=0,
                            fade_style=grey,
                            fade_indices=all_mode_indices,
                        )
                    )
                    time.sleep(_FRAME_TIME)
                # Final frame with normal styling (no fade override)
                w, h = console.size
                live.update(_build_mode_screen(selected, width=w, height=h, shimmer_tick=0.0, desc_reveal=0))
            select_time = time.monotonic()

            # ── Phase 1: Mode selection ───────────────────────────────────────
            while True:
                key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()

                if key in ("up", "left", "scroll_up", "down", "right", "scroll_down"):
                    # Coalesce a fast wheel/held-key burst into one net move + one
                    # repaint, so the animated mode carousel doesn't stutter.
                    _delta = coalesce_steps(
                        key,
                        read_key,
                        down=("down", "right", "scroll_down"),
                        up=("up", "left", "scroll_up"),
                    )
                    if _delta:
                        selected = (selected + _delta) % n
                        select_time = time.monotonic()
                    else:
                        continue  # net-zero burst — nothing moved, skip the repaint
                elif key == "enter":
                    mode = _MODE_CARDS[selected]
                    if mode["available"]:
                        break
                    continue
                elif key in ("q", "esc"):
                    return None
                elif key == "t":
                    # Toggle the rotating tips on/off and persist the choice. The
                    # live.update() at the bottom of the loop re-renders with the
                    # new state, so the tip banner hides/shows instantly.
                    from yeaboi.config import is_tips_enabled, set_tips_enabled

                    set_tips_enabled(not is_tips_enabled())
                elif key == "c":
                    # Open the Changelog page (bottom-left hint). Handled inline
                    # like `t` — no break, so returning falls straight back into
                    # this loop and the frame update below repaints mode select.
                    logger.info("changelog opened from mode select")
                    play_wordmark_intro(console, live, "Changelog", "rgb(160,160,180)", frame_time=_FRAME_TIME)
                    _run_changelog_page(console, live, read_key, _FRAME_TIME, _supports_timeout)
                    select_time = time.monotonic()  # restart the description typewriter

                elapsed = time.monotonic() - select_time
                reveal = elapsed * _DESC_SCROLL_SPEED  # float for sub-char fade

                w, h = console.size
                tick = time.monotonic() - start_time
                live.update(
                    _build_mode_screen(
                        selected,
                        width=w,
                        height=h,
                        shimmer_tick=tick,
                        desc_reveal=reveal,
                    )
                )

            # ── Phase 2: Transition ───────────────────────────────────────────
            chosen = _MODE_CARDS[selected]
            all_indices = list(range(n))
            others = [i for i in all_indices if i != selected]
            base_r, base_g, base_b = COLOR_RGB.get(chosen["color"], (180, 180, 180))
            base_style = f"bold rgb({base_r},{base_g},{base_b})"

            # 2a: Pulse the selected mode
            for frame in range(12):
                t = frame / 11
                intensity = math.sin(t * math.pi)
                r = int(base_r + (255 - base_r) * intensity)
                g = int(base_g + (255 - base_g) * intensity)
                b = int(base_b + (255 - base_b) * intensity)
                pulse_style = f"bold rgb({r},{g},{b})"
                w, h = console.size
                live.update(
                    _build_mode_screen(
                        selected,
                        width=w,
                        height=h,
                        visible=all_indices,
                        fade_style=pulse_style,
                        fade_indices=[selected],
                    )
                )
                time.sleep(_FRAME_TIME)

            # 2b: Fade out unselected modes
            for grey in FADE_OUT_LEVELS:
                w, h = console.size
                live.update(
                    _build_mode_screen(
                        selected,
                        width=w,
                        height=h,
                        visible=all_indices,
                        fade_style=grey,
                        fade_indices=others,
                        selected_style=base_style,
                    )
                )
                time.sleep(_FRAME_TIME)

            # 2c: Slide Planning title + description from center to top.
            # Description fades out as the title slides up.
            w, h = console.size
            inner_h = h - 4
            block_h = 2  # title(6) only — description disappears on selection
            start_offset = max(0, (inner_h - block_h) // 2)
            end_offset = 1  # one blank line above title to match project list layout

            slide_frames = 15
            for frame in range(slide_frames + 1):
                t = frame / slide_frames
                eased = ease_out_cubic(t)
                current_offset = int(start_offset + (end_offset - start_offset) * eased)
                w, h = console.size
                live.update(
                    _build_slide_frame(
                        chosen,
                        top_offset=current_offset,
                        width=w,
                        height=h,
                        style=base_style,
                    )
                )
                time.sleep(_FRAME_TIME)

            # ── Route: Team Analysis mode → dedicated analysis flow ──────
            if chosen["key"] == "team-analysis":
                logger.info("Analysis mode selected")
                # Route all records to logs/analysis/analysis.log while the
                # analysis flow runs. The branch is too large for a `with`
                # block, so it detaches explicitly at both `continue` exits.
                attach_mode_handler("analysis")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                from yeaboi.azdevops_sync import is_azdevops_board_configured as _azdevops_check
                from yeaboi.jira_sync import is_jira_configured as _jira_check

                _jira_ok = _jira_check()
                _azdevops_ok = _azdevops_check()
                _board_configured = _jira_ok or _azdevops_ok

                if not _board_configured:
                    # No board configured — show message and return to mode select.
                    # Re-render each frame so the ANALYSIS title keeps shimmering.
                    _br_anim0 = time.monotonic()  # shimmer title clock
                    while True:
                        w, h = console.size
                        live.update(
                            _build_project_export_success_screen(
                                "No board configured.\n\n"
                                "Set JIRA_BASE_URL + JIRA_API_TOKEN\n"
                                "or AZURE_DEVOPS_ORG_URL + AZURE_DEVOPS_TOKEN\n"
                                "in your .env file.",
                                width=w,
                                height=h,
                                subtitle="Board required",
                                hint="Press any key to go back.",
                                mode="analysis",
                                shimmer_tick=time.monotonic() - _br_anim0,
                            )
                        )
                        k = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                        if k:
                            break
                    _restart_mode_select = True
                    _skip_fade_in = True
                    detach_mode_handler("analysis")
                    continue

                # Load existing team profiles
                _profiles_for_analysis: list = []
                try:
                    from datetime import UTC, datetime

                    from yeaboi.team_profile import TeamProfileStore

                    _tp_db = _ana_dbp
                    if _tp_db.exists():
                        with TeamProfileStore(_tp_db) as _tp_store:
                            _raw_profiles = _tp_store.list_profiles()
                        for _rp in _raw_profiles:
                            days = 0
                            if _rp.updated_at:
                                try:
                                    _up = datetime.fromisoformat(_rp.updated_at)
                                    days = (datetime.now(UTC) - _up).days
                                except Exception:
                                    pass
                            # Check if preview flow was completed for this profile
                            _is_complete = False
                            try:
                                _a_sessions = _tp_store._conn.execute(
                                    "SELECT last_node_completed FROM sessions_meta "
                                    "WHERE session_mode = 'analysis' AND project_name LIKE ? "
                                    "ORDER BY last_modified DESC LIMIT 1",
                                    (f"%{_rp.project_key}%",),
                                ).fetchone()
                                if _a_sessions and _a_sessions[0] in ("complete", "done"):
                                    _is_complete = True
                            except Exception:
                                pass
                            _profiles_for_analysis.append(
                                ProfileSummary(
                                    team_id=_rp.team_id,
                                    source=_rp.source,
                                    project_key=_rp.project_key,
                                    sample_sprints=_rp.sample_sprints,
                                    velocity_avg=_rp.velocity_avg,
                                    sample_stories=_rp.sample_stories,
                                    updated="today" if days == 0 else (f"{days} day{'s' if days != 1 else ''} ago"),
                                    staleness_days=days,
                                    preview_complete=_is_complete,
                                )
                            )
                except Exception:
                    pass

                # Load resumable analysis sessions
                _ana_sessions: list[dict] = []
                try:
                    from yeaboi.sessions import SessionStore as _SessStore

                    _sess_db = _ana_dbp
                    if _sess_db.exists():
                        with _SessStore(_sess_db) as _ss:
                            _ana_sessions = _ss.list_analysis_sessions()
                except Exception:
                    pass

                logger.info(
                    "Analysis mode: %d profiles, %d sessions, jira=%s, azdevops=%s",
                    len(_profiles_for_analysis),
                    len(_ana_sessions),
                    _jira_ok,
                    _azdevops_ok,
                )

                # Always one button; board picker popup shown if both configured
                _ana_labels = ["+ New Analysis"]

                # Show profile list or go straight to analysis
                _ana_items = _profiles_for_analysis + _ana_labels  # type: ignore[operator]
                _ana_selected = 0
                _ana_n = len(_profiles_for_analysis) + len(_ana_labels)

                # Stagger reveal
                _reveal_target = float(_ana_n)
                _cards_visible = 0.0
                _reveal_speed = 15.0
                _reveal_start = time.monotonic()
                while _cards_visible < _reveal_target:
                    dt_r = time.monotonic() - _reveal_start
                    _cards_visible = min(_reveal_target, dt_r * _reveal_speed)
                    w, h = console.size
                    live.update(
                        _build_project_list_screen(
                            [],
                            _ana_selected,
                            width=w,
                            height=h,
                            cards_visible=_cards_visible,
                            card_fade=1.0,
                            jira_enabled=_jira_ok,
                            azdevops_enabled=_azdevops_ok,
                            profiles=_profiles_for_analysis,
                            new_analysis_labels=_ana_labels,
                            mode="analysis",
                            shimmer_tick=dt_r,
                        )
                    )
                    time.sleep(_FRAME_TIME)

                # Analysis mode interaction loop
                _team_popup_result = ""
                _ana_focus = 0
                _ana_card_fade = 1.0
                _ana_restart = True
                while _ana_restart:
                    _ana_restart = False
                    _ana_focus = 0
                    _ana_action_btns = 0.0
                    _has_prof = _profiles_for_analysis and _ana_selected < len(_profiles_for_analysis)
                    _ana_action_btns_target = 2.0 if _has_prof else 0.0
                    _ana_del_fade = 0.0
                    _ana_exp_fade = 0.0
                    _ana_export_submenu = False
                    _ana_sub_sel = 0
                    _ana_sub_html_fade = 0.0
                    _ana_sub_md_fade = 0.0
                    _ana_sub_visible = 0.0
                    _ana_sub_visible_target = 0.0
                    _ana_del_popup_open = False
                    _ana_del_popup_t = 0.0
                    _ana_del_popup_target = 0.0
                    _ana_del_popup_name = ""
                    _ana_del_popup_pulse = 0.0
                    _ana_del_popup_flash = 0.0
                    _ana_del_pending = False
                    _ana_prev = time.monotonic()
                    _ana_anim0 = _ana_prev  # shimmer title clock

                    while True:
                        key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                        _is_profile = _ana_selected < len(_profiles_for_analysis)
                        _is_analysis_btn = _ana_selected >= len(_profiles_for_analysis)

                        # ── Export submenu mode ───────────────────────────
                        if _ana_export_submenu and key:
                            if key == "left":
                                _ana_sub_sel = max(0, _ana_sub_sel - 1)
                                _ana_sub_html_fade = 1.0 if _ana_sub_sel == 0 else 0.0
                                _ana_sub_md_fade = 1.0 if _ana_sub_sel == 1 else 0.0
                            elif key == "right":
                                _ana_sub_sel = min(1, _ana_sub_sel + 1)
                                _ana_sub_html_fade = 1.0 if _ana_sub_sel == 0 else 0.0
                                _ana_sub_md_fade = 1.0 if _ana_sub_sel == 1 else 0.0
                            elif key == "enter":
                                _sel_p = _profiles_for_analysis[_ana_selected]
                                _tp_db = _ana_dbp
                                _full_p = None
                                _st_ex: dict | None = None
                                if _tp_db.exists():
                                    from yeaboi.team_profile import TeamProfileStore

                                    with TeamProfileStore(_tp_db) as _s:
                                        _full_p, _st_ex = _s.load_with_examples(_sel_p.team_id)
                                if _full_p:
                                    from yeaboi.agent.ceremony_history import gather_ceremony_context

                                    _cer = gather_ceremony_context(_full_p.project_key)
                                    if _ana_sub_sel == 0:
                                        from yeaboi.team_profile_exporter import export_team_profile_html

                                        _ep = export_team_profile_html(_full_p, examples=_st_ex, ceremony=_cer)
                                    else:
                                        from yeaboi.team_profile_exporter import export_team_profile_md

                                        _ep = export_team_profile_md(_full_p, examples=_st_ex, ceremony=_cer)
                                    w, h = console.size
                                    live.update(
                                        _build_project_export_success_screen(
                                            str(_ep),
                                            width=w,
                                            height=h,
                                            subtitle="Team profile exported",
                                            mode="analysis",
                                        )
                                    )
                                    _et = time.monotonic()
                                    while True:
                                        ek = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                                        if time.monotonic() - _et > 1.5 and ek:
                                            break
                                _ana_export_submenu = False
                                _ana_sub_visible_target = 0.0
                                _ana_sub_html_fade = 0.0
                                _ana_sub_md_fade = 0.0
                                _ana_exp_fade = 1.0
                            elif key in ("esc", "q"):
                                _ana_export_submenu = False
                                _ana_sub_visible_target = 0.0
                                _ana_sub_html_fade = 0.0
                                _ana_sub_md_fade = 0.0
                                _ana_exp_fade = 1.0
                            continue

                        # ── Delete confirmation popup ─────────────────
                        if _ana_del_popup_open and key:
                            if key == "enter":
                                _ana_del_popup_flash = 1.0
                                _ana_del_pending = True
                            elif key in ("esc", "q"):
                                _ana_del_popup_target = 0.0
                            continue

                        # Perform delete after popup slides out
                        if _ana_del_popup_open and _ana_del_popup_target == 0.0 and _ana_del_popup_t <= 0:
                            if _ana_del_pending:
                                try:
                                    from yeaboi.team_profile import TeamProfileStore

                                    _tp_db = _ana_dbp
                                    if _tp_db.exists():
                                        _del_p = _profiles_for_analysis[_ana_selected]
                                        with TeamProfileStore(_tp_db) as _s:
                                            _s.delete(_del_p.team_id)
                                    _profiles_for_analysis.pop(_ana_selected)
                                    _ana_n = len(_profiles_for_analysis) + len(_ana_labels)
                                    _ana_selected = min(_ana_selected, _ana_n - 1)
                                    _ana_focus = 0
                                    _ana_action_btns = 0.0
                                    _ana_del_fade = 0.0
                                    _ana_exp_fade = 0.0
                                    _has_prof = _profiles_for_analysis and _ana_selected < len(_profiles_for_analysis)
                                    _ana_action_btns_target = 2.0 if _has_prof else 0.0
                                except Exception:
                                    pass
                            _ana_del_popup_open = False
                            _ana_del_popup_name = ""
                            _ana_del_pending = False

                        if key in ("up", "scroll_up", "down", "scroll_down"):
                            _delta = coalesce_steps(key, read_key, down=("down", "scroll_down"), up=("up", "scroll_up"))
                            if not _delta:
                                continue
                            _ana_selected = (_ana_selected + _delta) % _ana_n
                            _ana_focus = 0
                            _ana_action_btns = 0.0
                            _is_profile = _ana_selected < len(_profiles_for_analysis)
                            _ana_action_btns_target = 2.0 if _is_profile else 0.0
                            _ana_del_fade = 0.0
                            _ana_exp_fade = 0.0
                            _ana_export_submenu = False
                            _ana_sub_visible_target = 0.0
                        elif key == "left":
                            if _ana_focus > 0:
                                _ana_focus -= 1
                            _ana_del_fade = 0.0 if _ana_focus != 1 else 1.0
                            _ana_exp_fade = 0.0 if _ana_focus != 2 else 1.0
                        elif key == "right":
                            if _is_profile and _ana_focus < 2:
                                _ana_focus += 1
                            _ana_del_fade = 0.0 if _ana_focus != 1 else 1.0
                            _ana_exp_fade = 0.0 if _ana_focus != 2 else 1.0
                        elif key == "enter":
                            if _is_profile and _ana_focus == 0:
                                # View profile results
                                _sel_p = _profiles_for_analysis[_ana_selected]
                                from yeaboi.team_profile import TeamProfileStore

                                _tp_db = _ana_dbp
                                _full = None
                                _stored_ex: dict | None = None
                                if _tp_db.exists():
                                    with TeamProfileStore(_tp_db) as _s:
                                        _full, _stored_ex = _s.load_with_examples(
                                            _sel_p.team_id,
                                        )
                                if _full:
                                    _res = _run_team_analysis_results(
                                        live,
                                        console,
                                        read_key,
                                        _FRAME_TIME,
                                        _supports_timeout,
                                        _full,
                                        _stored_ex,
                                    )
                                    if _res == "continue":
                                        from yeaboi.agent.nodes import _format_team_calibration

                                        _si_text = _format_team_calibration(
                                            _full,
                                            examples=_stored_ex,
                                        )
                                        if _si_text.strip():
                                            _si_resume = _load_ana_session(
                                                _full.project_key if _full else "",
                                            )
                                            # Skip the confirmation when resuming a
                                            # ticket session already mid-generation —
                                            # the user confirmed on the first pass.
                                            _resuming = bool(_si_resume) and _si_resume.get("last_page") in (
                                                "epic",
                                                "stories",
                                                "tasks",
                                                "sprint",
                                            )
                                            if _resuming or _confirm_ticket_generation(
                                                live,
                                                console,
                                                read_key,
                                                _FRAME_TIME,
                                                _supports_timeout,
                                                subtitle=f"{_full.source}/{_full.project_key}" if _full else "",
                                            ):
                                                _run_preview_flow(
                                                    live,
                                                    console,
                                                    read_key,
                                                    _FRAME_TIME,
                                                    _supports_timeout,
                                                    _si_text,
                                                    _full,
                                                    _stored_ex,
                                                    resume_state=_si_resume,
                                                )
                                continue
                            elif _is_profile and _ana_focus == 1:
                                # Delete profile — open confirmation popup
                                _sel_p = _profiles_for_analysis[_ana_selected]
                                _ana_del_popup_open = True
                                _ana_del_popup_target = 1.0
                                _ana_del_popup_name = f"{_sel_p.source}/{_sel_p.project_key}"
                                _ana_del_popup_pulse = 0.0
                                _ana_del_popup_flash = 0.0
                                _ana_del_pending = False
                                continue
                            elif _is_profile and _ana_focus == 2:
                                # Export → open submenu
                                _ana_export_submenu = True
                                _ana_sub_sel = 0
                                _ana_sub_visible_target = 2.0
                                _ana_sub_html_fade = 1.0
                                _ana_sub_md_fade = 0.0
                                _ana_exp_fade = 0.0
                                continue
                            elif _is_analysis_btn:
                                # New analysis — if both boards, show picker popup
                                if _jira_ok and _azdevops_ok:
                                    from rich.console import Group
                                    from rich.text import Text

                                    _ana_popup_sel = 0  # 0=Jira, 1=AzDO
                                    _ana_popup_open = True
                                    _ana_popup_tick = 0.0
                                    while _ana_popup_open:
                                        _ana_popup_tick += _FRAME_TIME
                                        w, h = console.size
                                        import rich.box as _rbox
                                        from rich.padding import Padding  # noqa: F811
                                        from rich.panel import Panel as _PickPanel

                                        from yeaboi.ui.shared._components import analysis_title as _at

                                        _ana_title = _at()

                                        # Styled board picker with green accent
                                        _accent = "#22c55e"
                                        _pick_inner_w = min(w - 10, 50)
                                        _pick_msg = "Which board to analyse?"
                                        _pick_pad = max(0, (_pick_inner_w - len(_pick_msg)) // 2)

                                        _pick_body: list = [Text("")]
                                        _pick_body.append(
                                            Text(
                                                " " * _pick_pad + _pick_msg,
                                                style="bold white",
                                                justify="left",
                                            )
                                        )
                                        _pick_body.append(Text(""))

                                        # Buttons with green highlight
                                        _btn_line = Text(justify="center")
                                        for bi, bl in enumerate(["Jira", "Azure DevOps"]):
                                            if bi > 0:
                                                _btn_line.append("     ")
                                            if bi == _ana_popup_sel:
                                                _btn_line.append(
                                                    f" [ {bl} ] ",
                                                    style=f"bold {_accent}",
                                                )
                                            else:
                                                _btn_line.append(
                                                    f"   {bl}   ",
                                                    style="dim",
                                                )
                                        _pick_body.append(_btn_line)
                                        _pick_body.append(Text(""))

                                        _hint = Text(
                                            "← → select  ·  Enter confirm  ·  Esc cancel",
                                            style="rgb(60,60,80)",
                                            justify="center",
                                        )
                                        _pick_body.append(_hint)

                                        # Center the popup vertically
                                        _popup_h = 7
                                        _top_pad = max(0, (h - 8 - _popup_h) // 2)
                                        _bot_pad = max(0, h - 8 - _popup_h - _top_pad)

                                        live.update(
                                            _PickPanel(
                                                Group(
                                                    _ana_title,
                                                    *[Text("") for _ in range(_top_pad)],
                                                    Padding(
                                                        _PickPanel(
                                                            Group(*_pick_body),
                                                            border_style=_accent,
                                                            box=_rbox.ROUNDED,
                                                            width=_pick_inner_w + 4,
                                                            padding=(0, 2),
                                                        ),
                                                        (0, 0, 0, max(0, (w - _pick_inner_w - 8) // 2)),
                                                    ),
                                                    *[Text("") for _ in range(_bot_pad)],
                                                ),
                                                border_style="white",
                                                box=_rbox.ROUNDED,
                                                expand=True,
                                                height=h,
                                                padding=(1, 2),
                                            )
                                        )
                                        pk = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                                        if pk == "left":
                                            _ana_popup_sel = 0
                                        elif pk == "right":
                                            _ana_popup_sel = 1
                                        elif pk == "enter":
                                            _team_popup_result = (
                                                "analyse_jira" if _ana_popup_sel == 0 else "analyse_azdevops"
                                            )
                                            _ana_popup_open = False
                                        elif pk in ("esc", "q"):
                                            _ana_popup_open = False
                                    if _team_popup_result.startswith("analyse"):
                                        break
                                    continue  # user pressed Esc on picker
                                elif _jira_ok:
                                    _team_popup_result = "analyse"
                                else:
                                    _team_popup_result = "analyse_azdevops"
                                break
                        elif key in ("esc", "q"):
                            _restart_mode_select = True
                            _skip_fade_in = True
                            break

                        # Animate
                        _now = time.monotonic()
                        _dt = _now - _ana_prev
                        _ana_prev = _now
                        _astep = _dt * 12.0
                        if _ana_action_btns < _ana_action_btns_target:
                            _ana_action_btns = min(_ana_action_btns + _astep, _ana_action_btns_target)
                        elif _ana_action_btns > _ana_action_btns_target:
                            _ana_action_btns = max(_ana_action_btns - _astep, _ana_action_btns_target)
                        if _ana_sub_visible < _ana_sub_visible_target:
                            _ana_sub_visible = min(_ana_sub_visible + _astep, _ana_sub_visible_target)
                        elif _ana_sub_visible > _ana_sub_visible_target:
                            _ana_sub_visible = max(_ana_sub_visible - _astep, _ana_sub_visible_target)
                        # Delete popup animation
                        if _ana_del_popup_t < _ana_del_popup_target:
                            _ana_del_popup_t = min(_ana_del_popup_t + _astep * 0.5, _ana_del_popup_target)
                        elif _ana_del_popup_t > _ana_del_popup_target:
                            _ana_del_popup_t = max(_ana_del_popup_t - _astep * 0.5, _ana_del_popup_target)
                        if _ana_del_popup_open:
                            _ana_del_popup_pulse += _dt * 4.0
                        if _ana_del_popup_flash > 0:
                            _ana_del_popup_flash = max(0.0, _ana_del_popup_flash - _dt * 3.0)
                            if _ana_del_popup_flash <= 0.1 and _ana_del_pending:
                                _ana_del_popup_target = 0.0

                        w, h = console.size
                        live.update(
                            _build_project_list_screen(
                                [],
                                _ana_selected,
                                width=w,
                                height=h,
                                jira_enabled=_jira_ok,
                                azdevops_enabled=_azdevops_ok,
                                profiles=_profiles_for_analysis,
                                new_analysis_labels=_ana_labels,
                                profile_focus=_ana_focus,
                                profile_del_fade=_ana_del_fade,
                                profile_card_fade=1.0,
                                profile_action_btns_visible=_ana_action_btns,
                                profile_exp_fade=_ana_exp_fade,
                                profile_export_submenu=_ana_export_submenu,
                                profile_submenu_sel=_ana_sub_sel,
                                profile_submenu_html_fade=_ana_sub_html_fade,
                                profile_submenu_md_fade=_ana_sub_md_fade,
                                profile_submenu_visible=_ana_sub_visible,
                                delete_popup_name=_ana_del_popup_name,
                                delete_popup_t=_ana_del_popup_t,
                                delete_popup_pulse=_ana_del_popup_pulse,
                                delete_popup_flash=_ana_del_popup_flash,
                                mode="analysis",
                                shimmer_tick=_now - _ana_anim0,
                            )
                        )

                    if _restart_mode_select:
                        break  # break out of _ana_restart loop → back to mode select

                    # Run team analysis (reuse Phase 3a logic)
                    if _team_popup_result.startswith("analyse"):
                        import threading

                        from yeaboi.team_profile import TeamProfileStore
                        from yeaboi.tools.team_learning import (
                            _fetch_azdevops_history,
                            _fetch_jira_history,
                            _run_parallel_analysis,
                        )

                        if _team_popup_result == "analyse_jira":
                            _ta_source = "jira"
                        elif _team_popup_result == "analyse_azdevops":
                            _ta_source = "azdevops"
                        else:
                            _ta_source = "jira" if _jira_ok else "azdevops"

                        _ta_project_key = ""
                        _ta_team_name = ""
                        try:
                            if _ta_source == "jira":
                                from yeaboi.config import get_jira_project_key

                                _ta_project_key = get_jira_project_key() or ""
                            else:
                                from yeaboi.config import (
                                    get_azure_devops_project,
                                    get_azure_devops_team,
                                )

                                _ta_project_key = get_azure_devops_project() or ""
                                _ta_team_name = get_azure_devops_team() or ""
                        except Exception:
                            pass

                        _ta_progress: list[str] = ["Fetching sprint history\u2026"]
                        _ta_profile_box: list = [None]
                        _ta_examples_box: list = [None]
                        _ta_sprint_names_box: list = [[]]
                        _ta_error_box: list[str] = [""]
                        _ta_done = threading.Event()

                        def _run_team_analysis_mode():
                            try:
                                if _ta_source == "jira":
                                    sprint_data = _fetch_jira_history(_ta_project_key, 8)
                                else:
                                    sprint_data = _fetch_azdevops_history(_ta_project_key, 8)
                                if not sprint_data:
                                    _ta_error_box[0] = "No closed sprints found."
                                else:
                                    _ta_sprint_names_box[0] = [sd.get("sprint_name", "") for sd in sprint_data]
                                    _result = _run_parallel_analysis(
                                        _ta_source,
                                        _ta_project_key or "unknown",
                                        sprint_data,
                                        _ta_progress,
                                    )
                                    _ta_profile_box[0] = _result[0]
                                    _ta_examples_box[0] = _result[1]
                            except Exception as exc:
                                from yeaboi.ui.session._utils import _classify_api_error

                                _ta_error_box[0] = _classify_api_error(exc)
                            finally:
                                _ta_done.set()

                        _ta_thread_start = time.monotonic()
                        _ta_thread = threading.Thread(
                            target=_run_team_analysis_mode,
                            daemon=True,
                        )
                        logger.info(
                            "Analysis: starting %s analysis for %s",
                            _ta_source,
                            _ta_project_key,
                        )
                        _ta_thread.start()

                        from yeaboi.ui.mode_select.screens._screens_secondary import (
                            _build_analysis_progress_screen,
                        )

                        _ta_anim_tick = 0.0
                        while not _ta_done.is_set():
                            _ta_anim_tick += _FRAME_TIME
                            w, h = console.size
                            live.update(
                                _build_analysis_progress_screen(
                                    _ta_progress,
                                    width=w,
                                    height=h,
                                    elapsed=time.monotonic() - _ta_thread_start,
                                    anim_tick=_ta_anim_tick,
                                    source=_ta_source,
                                    mode="analysis",
                                )
                            )
                            time.sleep(_FRAME_TIME)
                        _ta_thread.join()

                        _ta_profile = _ta_profile_box[0]
                        _ta_duration = time.monotonic() - _ta_thread_start
                        if _ta_profile:
                            logger.info(
                                "Analysis completed in %.1fs: %d sprints, %d stories, vel=%.1f",
                                _ta_duration,
                                _ta_profile.sample_sprints,
                                _ta_profile.sample_stories,
                                _ta_profile.velocity_avg,
                            )
                        elif _ta_error_box[0]:
                            logger.error("Analysis failed: %s", _ta_error_box[0])
                        if _ta_profile:
                            # Attach AzDO team name to profile before saving
                            if _ta_team_name and not _ta_profile.team_name:
                                from dataclasses import replace as _dc_replace

                                _ta_profile = _dc_replace(_ta_profile, team_name=_ta_team_name)
                            # Save to the same DB every list/resume path reads from
                            # (_ana_dbp = ~/.yeaboi/data/sessions.db) so a just-finished
                            # analysis is visible immediately, not only after a restart.
                            with TeamProfileStore(_ana_dbp) as store:
                                store.save(_ta_profile, examples=_ta_examples_box[0])
                            try:
                                from yeaboi.team_profile_exporter import write_analysis_log

                                write_analysis_log(
                                    _ta_profile,
                                    examples=_ta_examples_box[0],
                                    sprint_names=_ta_sprint_names_box[0],
                                    duration_secs=_ta_duration,
                                )
                            except Exception:
                                pass

                            # Show results (overview + section cards)
                            _ta_examples = _ta_examples_box[0] or {}
                            _ta_sprint_names = _ta_sprint_names_box[0]
                            _res = _run_team_analysis_results(
                                live,
                                console,
                                read_key,
                                _FRAME_TIME,
                                _supports_timeout,
                                _ta_profile,
                                _ta_examples,
                                sprint_names=_ta_sprint_names,
                                team_name=_ta_team_name,
                            )
                            if _res == "continue":
                                global _ana_sid  # noqa: PLW0603

                                # Ask before generating tickets — separate the
                                # team/board analysis from ticket creation.
                                if _confirm_ticket_generation(
                                    live,
                                    console,
                                    read_key,
                                    _FRAME_TIME,
                                    _supports_timeout,
                                    subtitle=f"{_ta_profile.source}/{_ta_profile.project_key}" if _ta_profile else "",
                                ):
                                    from yeaboi.agent.nodes import _format_team_calibration
                                    from yeaboi.sessions import SessionStore as _AStore
                                    from yeaboi.sessions import make_session_id

                                    _ana_sid = make_session_id()
                                    try:
                                        with _AStore(_ana_dbp) as _as:
                                            _as.create_session(
                                                _ana_sid,
                                                _ta_profile.project_key if _ta_profile else "",
                                                mode="analysis",
                                            )
                                    except Exception:
                                        pass

                                    _instr_text = _format_team_calibration(
                                        _ta_profile,
                                        examples=_ta_examples,
                                    )
                                    if _instr_text.strip():
                                        _run_preview_flow(
                                            live,
                                            console,
                                            read_key,
                                            _FRAME_TIME,
                                            _supports_timeout,
                                            _instr_text,
                                            _ta_profile,
                                            _ta_examples,
                                            resume_state=None,
                                        )
                        elif _ta_error_box[0]:
                            w, h = console.size
                            live.update(
                                _build_project_export_success_screen(
                                    _ta_error_box[0],
                                    width=w,
                                    height=h,
                                    subtitle="Analysis failed",
                                    hint="Press any key to continue.",
                                    mode="analysis",
                                )
                            )
                            while True:
                                k = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                                if k:
                                    break

                        # Reload profiles and restart analysis list
                        try:
                            from datetime import UTC, datetime

                            from yeaboi.team_profile import TeamProfileStore

                            _tp_db = _ana_dbp
                            if _tp_db.exists():
                                with TeamProfileStore(_tp_db) as _tp_s:
                                    _raw2 = _tp_s.list_profiles()
                                _profiles_for_analysis = []
                                for _rp in _raw2:
                                    days = 0
                                    if _rp.updated_at:
                                        try:
                                            _up = datetime.fromisoformat(_rp.updated_at)
                                            days = (datetime.now(UTC) - _up).days
                                        except Exception:
                                            pass
                                    _profiles_for_analysis.append(
                                        ProfileSummary(
                                            team_id=_rp.team_id,
                                            source=_rp.source,
                                            project_key=_rp.project_key,
                                            sample_sprints=_rp.sample_sprints,
                                            velocity_avg=_rp.velocity_avg,
                                            sample_stories=_rp.sample_stories,
                                            updated="today"
                                            if days == 0
                                            else (f"{days} day{'s' if days != 1 else ''} ago"),
                                            staleness_days=days,
                                        )
                                    )
                        except Exception:
                            pass
                        _ana_n = len(_profiles_for_analysis) + len(_ana_labels)
                        _ana_selected = 0
                        _ana_restart = True
                        _team_popup_result = ""
                        continue

                    # Esc from analysis list → back to mode select
                    _restart_mode_select = True
                    _skip_fade_in = True

                # Always return to mode select after analysis mode exits
                detach_mode_handler("analysis")
                continue

            # 2d: Smooth fade-in — all cards appear together, opacity 0→1
            # See README: "Memory & State" — load persisted project history
            from yeaboi.persistence import load_projects as _load_projects

            projects = _load_projects()
            proj_selected = 0
            if projects:
                proj_n = len(projects) + 1
            else:
                proj_n = 2

            # Check which trackers are configured — used to show/dim submenu buttons.
            from yeaboi.azdevops_sync import is_azdevops_board_configured as _azdevops_check
            from yeaboi.jira_sync import is_jira_configured as _jira_check

            _jira_ok = _jira_check()
            _azdevops_ok = _azdevops_check()
            # Submenu has HTML(0), Markdown(1), then tracker buttons dynamically
            _submenu_max = 1 + (1 if _jira_ok else 0) + (1 if _azdevops_ok else 0)

            # Check team profile staleness for the popup on "+ New Project"
            _board_configured = _jira_ok or _azdevops_ok
            _staleness_days: int | None = None
            if _board_configured:
                try:
                    from yeaboi.team_profile import TeamProfileStore

                    _tp_db = _ana_dbp
                    if _tp_db.exists():
                        with TeamProfileStore(_tp_db) as _tp_store:
                            _tp_profiles = _tp_store.list_profiles()
                        # Filter to profiles matching the configured board(s)
                        _matching_profiles = []
                        for _tpp in _tp_profiles:
                            if _jira_ok and _tpp.source == "jira":
                                _matching_profiles.append(_tpp)
                            elif _azdevops_ok and _tpp.source == "azdevops":
                                _matching_profiles.append(_tpp)
                        if _matching_profiles:
                            from datetime import UTC
                            from datetime import datetime as _dt

                            _latest = _matching_profiles[0]
                            if _latest.updated_at:
                                try:
                                    _up = _dt.fromisoformat(_latest.updated_at)
                                    _staleness_days = (_dt.now(UTC) - _up).days
                                except Exception:
                                    pass
                except Exception:
                    pass
            logger.info(
                "Board config: jira=%s, azdevops=%s, staleness_days=%s",
                _jira_ok,
                _azdevops_ok,
                _staleness_days,
            )

            # ── Route: Daily Standup mode → dashboard + actions ──────────
            if chosen["key"] == "daily-standup":
                logger.info("Daily Standup mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                # Route all records to logs/standup/standup.log while the page runs.
                with mode_log("standup"):
                    _run_standup_page(console, live, read_key, _FRAME_TIME, _supports_timeout)
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Retro mode → collaborative board page ─────────────
            if chosen["key"] == "retro":
                logger.info("Retro mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                with mode_log("retro"):
                    _run_retro_page(console, live, read_key, _FRAME_TIME, _supports_timeout)
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Performance mode → per-engineer dashboard ─────────
            if chosen["key"] == "performance":
                logger.info("Performance mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                with mode_log("performance"):
                    _run_performance_page(console, live, read_key, _FRAME_TIME, _supports_timeout)
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Reporting mode → delivery-report page ─────────────
            if chosen["key"] == "reporting":
                logger.info("Reporting mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                with mode_log("reporting"):
                    _run_reporting_page(console, live, read_key, _FRAME_TIME, _supports_timeout)
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Usage mode → single-page dashboard ────────────────
            if chosen["key"] == "usage":
                logger.info("Usage mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                from yeaboi.ui.mode_select.screens._screens_secondary import _build_usage_screen

                _usage_data = _collect_usage_data()
                _u_scroll, _u_sel = 0, 0
                _u_scroll_meta: dict = {}
                _u_anim_start = time.monotonic()  # shimmer title + typewriter subtitle
                w, h = console.size
                live.update(
                    _build_usage_screen(
                        _usage_data,
                        scroll_offset=_u_scroll,
                        scroll_meta=_u_scroll_meta,
                        width=w,
                        height=h,
                        action_sel=_u_sel,
                        shimmer_tick=0.0,
                        sub_reveal=0.0,
                    )
                )
                logger.info("Usage page opened")
                while True:
                    k = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                    if k in SCROLL_KEYS:
                        _ns = coalesce_scroll(_u_scroll, k, _u_scroll_meta, read_key)
                        if _ns == _u_scroll:
                            continue
                        _u_scroll = _ns
                    elif k in ("enter", " ", "esc", "q"):
                        break
                    w, h = console.size
                    _u_elapsed = time.monotonic() - _u_anim_start
                    live.update(
                        _build_usage_screen(
                            _usage_data,
                            scroll_offset=_u_scroll,
                            scroll_meta=_u_scroll_meta,
                            width=w,
                            height=h,
                            action_sel=_u_sel,
                            shimmer_tick=_u_elapsed,
                            sub_reveal=_u_elapsed * _HEADER_SUB_SPEED,
                        )
                    )
                logger.info("Usage page closed")
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Settings mode → config viewer + setup wizard ────────
            if chosen["key"] == "settings":
                logger.info("Settings mode selected")
                play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)
                from yeaboi.ui.mode_select.screens._screens_secondary import _build_settings_screen

                _settings_data = _collect_settings_data()
                _s_scroll, _s_sel = 0, 0
                _s_scroll_meta: dict = {}
                _s_anim_start = time.monotonic()  # shimmer title + typewriter subtitle
                w, h = console.size
                live.update(
                    _build_settings_screen(
                        _settings_data,
                        scroll_offset=_s_scroll,
                        scroll_meta=_s_scroll_meta,
                        width=w,
                        height=h,
                        action_sel=_s_sel,
                        shimmer_tick=0.0,
                        sub_reveal=0.0,
                    )
                )
                while True:
                    sk = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                    if sk in SCROLL_KEYS:
                        _ns = coalesce_scroll(_s_scroll, sk, _s_scroll_meta, read_key)
                        if _ns == _s_scroll:
                            continue
                        _s_scroll = _ns
                    elif sk == "left":
                        _s_sel = max(0, _s_sel - 1)
                    elif sk == "right":
                        _s_sel = min(2, _s_sel + 1)
                    elif sk in ("enter", " "):
                        if _s_sel == 0:
                            # Configure — launch setup wizard
                            logger.info("Settings: launching setup wizard")
                            live.stop()
                            from yeaboi.setup_wizard import run_setup_wizard

                            run_setup_wizard(console)
                            # Reload config after wizard completes
                            from yeaboi.config import load_user_config

                            load_user_config()
                            _settings_data = _collect_settings_data()
                            logger.info("Settings: config reloaded after wizard")
                            live.start()
                        elif _s_sel == 1:
                            # Log Level — cycle, persist to .env, apply live
                            from yeaboi.config import get_log_level, set_log_level
                            from yeaboi.logging_setup import apply_level

                            _new_level = _next_log_level(get_log_level())
                            set_log_level(_new_level)
                            apply_level(_new_level)
                            _settings_data = _collect_settings_data()
                            logger.info("Settings: log level cycled to %s", _new_level)
                        else:
                            logger.info("Settings: user pressed Back")
                            break
                    elif sk in ("esc", "q"):
                        logger.info("Settings: user pressed Esc")
                        break
                    w, h = console.size
                    _s_elapsed = time.monotonic() - _s_anim_start
                    live.update(
                        _build_settings_screen(
                            _settings_data,
                            scroll_offset=_s_scroll,
                            scroll_meta=_s_scroll_meta,
                            width=w,
                            height=h,
                            action_sel=_s_sel,
                            shimmer_tick=_s_elapsed,
                            sub_reveal=_s_elapsed * _HEADER_SUB_SPEED,
                        )
                    )
                _restart_mode_select = True
                _skip_fade_in = True
                continue

            # ── Route: Planning mode → project list + session ────────────
            # Reached only when none of the mode branches above matched, i.e.
            # chosen["key"] == "project-planning". Runs once, before the project
            # list loop, so the intro plays a single time per Planning entry.
            play_wordmark_intro(console, live, chosen["title"], chosen["color"], frame_time=_FRAME_TIME)

            # Staggered vertical reveal — cards pop in one by one, fast.
            _reveal_target = float(proj_n)
            _cards_visible = 0.0
            _reveal_speed = 15.0  # cards per second (~1 card every 4 frames)
            _reveal_start = time.monotonic()
            while _cards_visible < _reveal_target:
                dt_r = time.monotonic() - _reveal_start
                _cards_visible = min(_reveal_target, dt_r * _reveal_speed)
                w, h = console.size
                live.update(
                    _build_project_list_screen(
                        projects,
                        proj_selected,
                        width=w,
                        height=h,
                        cards_visible=_cards_visible,
                        card_fade=1.0,
                        jira_enabled=_jira_ok,
                        azdevops_enabled=_azdevops_ok,
                        shimmer_tick=dt_r,
                    )
                )
                time.sleep(_FRAME_TIME)

            # ── Phase 3: Project list interaction ─────────────────────────────
            # focus: 0 = project card, 1 = Delete button, 2 = Export button.
            # Up/Down navigates between projects (resets focus to card).
            # Left/Right navigates between card ↔ Delete ↔ Export within a row.
            # Enter activates the focused element (open project, delete, export).
            #
            # When Export is activated, a split submenu [HTML | Markdown] slides
            # out from the Export button. Left/Right switches between the two
            # halves; Enter exports; Esc closes the submenu.
            #
            # Button colour animation: buttons start grey and smoothly fade
            # to their accent colour when focused, then fade back to grey
            # when focus leaves.  del_fade_target / exp_fade_target track the
            # desired end state; del_fade / exp_fade are the animated values.
            #
            # _restart_project_list: set to True when a session ends (Esc or
            # completed) so we loop back to this point from Phase 4.
            _restart_project_list = True
            while _restart_project_list:
                _restart_project_list = False
                focus = 0
                del_fade = 0.0  # current animated value 0.0 (grey) → 1.0 (colour)
                exp_fade = 0.0
                card_fade = 1.0  # start fully visible for initially selected card
                pulse = 0.0  # one-shot white flash on Enter (decays from 1.0 → 0.0)
                del_fade_target = 0.0
                exp_fade_target = 0.0
                card_fade_target = 1.0
                fade_speed = 6.0  # units per second — full transition ≈ 0.17s

                _is_project_row = lambda: projects and proj_selected < len(projects)  # noqa: E731

                # Action buttons (Delete/Export) stagger-reveal on the selected row
                action_btns_visible = 0.0
                action_btns_visible_target = 2.0 if _is_project_row() else 0.0

                # Export submenu state — the split [HTML | Markdown | Jira] panel
                export_submenu_open = False
                submenu_sel = 0  # 0 = HTML, 1 = Markdown, 2 = Jira
                submenu_html_fade = 0.0
                submenu_md_fade = 0.0
                submenu_jira_fade = 0.0
                submenu_azdevops_fade = 0.0
                submenu_html_fade_target = 0.0
                submenu_md_fade_target = 0.0
                submenu_jira_fade_target = 0.0
                submenu_azdevops_fade_target = 0.0
                submenu_visible = 0.0
                submenu_visible_target = 0.0

                # Delete popup state — non-blocking overlay instead of full-screen modal.
                # The popup slides up from the bottom of the project list screen.
                delete_popup_open = False
                delete_popup_t = 0.0  # animated 0→1 (slide-up progress)
                delete_popup_target = 0.0  # 0.0 = hidden, 1.0 = visible
                delete_popup_name = ""
                delete_popup_pulse = 0.0  # sine-wave phase for red pulsing
                delete_popup_flash = 0.0  # white flash on confirm (1→0 decay)
                _delete_pending = False  # True after Enter confirm, delete after slide-out

                # Team analysis popup state — staleness prompt when profile >30d old
                team_popup_open = False
                team_popup_t = 0.0
                team_popup_target = 0.0
                team_popup_sel = 0  # 0 = Yes Analyse, 1 = Skip
                team_popup_pulse = 0.0
                _team_popup_result = ""  # "analyse" or "skip"
                _team_popup_msg = ""  # dynamic staleness message

                prev_tick = time.monotonic()
                _list_anim0 = prev_tick  # shimmer title clock

                while True:
                    key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()

                    # ── Export submenu mode ────────────────────────────────────
                    # When the submenu is open, capture all keys here. Left/Right
                    # switches between HTML and Markdown; Enter exports; Esc closes.
                    # Build dynamic submenu index → action mapping
                    _submenu_actions = ["html", "markdown"]
                    if _jira_ok:
                        _submenu_actions.append("jira")
                    if _azdevops_ok:
                        _submenu_actions.append("azdevops")

                    def _update_submenu_fades():
                        nonlocal submenu_html_fade_target, submenu_md_fade_target
                        nonlocal submenu_jira_fade_target, submenu_azdevops_fade_target
                        submenu_html_fade_target = 1.0 if submenu_sel == 0 else 0.0
                        submenu_md_fade_target = 1.0 if submenu_sel == 1 else 0.0
                        _jira_idx = _submenu_actions.index("jira") if "jira" in _submenu_actions else -1
                        _azdo_idx = _submenu_actions.index("azdevops") if "azdevops" in _submenu_actions else -1
                        submenu_jira_fade_target = 1.0 if submenu_sel == _jira_idx else 0.0
                        submenu_azdevops_fade_target = 1.0 if submenu_sel == _azdo_idx else 0.0

                    if export_submenu_open:
                        if key == "left":
                            submenu_sel = max(0, submenu_sel - 1)
                            _update_submenu_fades()
                        elif key == "right":
                            submenu_sel = min(_submenu_max, submenu_sel + 1)
                            _update_submenu_fades()
                        elif key == "enter":
                            project = projects[proj_selected]
                            path = None
                            _action = _submenu_actions[submenu_sel] if submenu_sel < len(_submenu_actions) else ""
                            if _action == "html":
                                from yeaboi.persistence import export_project_html

                                path = export_project_html(project.id)
                            elif _action == "markdown":
                                from yeaboi.persistence import export_project_md

                                path = export_project_md(project.id)
                            elif _action in ("jira", "azdevops"):
                                # Tracker export — full sync: Epic + Stories + Tasks + Sprints
                                import threading

                                from yeaboi.persistence import (
                                    load_graph_state,
                                    save_graph_state,
                                    save_project_snapshot,
                                )

                                _tracker_label = "Jira" if _action == "jira" else "Azure DevOps"
                                if _action == "jira":
                                    from yeaboi.jira_sync import sync_all_to_jira as _sync_all_fn
                                else:
                                    from yeaboi.azdevops_sync import sync_all_to_azdevops as _sync_all_fn

                                if True:
                                    gs = load_graph_state(project.id)
                                    if not gs:
                                        path = "No saved state for this project"
                                    else:
                                        # Run sync in background thread with live progress
                                        _sync_result_box: list = [None, None]  # [result, error]
                                        _sync_state_box: list = [None]
                                        _sync_done = threading.Event()
                                        # Shared progress state: log of completed items + current active item
                                        _sync_log: list[str] = []
                                        _sync_current: list[str] = ["Starting..."]
                                        _sync_counter: list[int] = [0, 0]  # [current, total]

                                        def _on_sync_progress(current, total, desc):
                                            _sync_counter[0] = current
                                            _sync_counter[1] = total
                                            if _sync_current[0] and _sync_current[0] != "Starting...":
                                                _sync_log.append(f"  ✓ {_sync_current[0]}")
                                            _sync_current[0] = desc

                                        def _run_jira_sync():
                                            try:
                                                r, s = _sync_all_fn(gs, on_progress=_on_sync_progress)
                                                _sync_result_box[0] = r
                                                _sync_state_box[0] = s
                                            except Exception as exc:
                                                _sync_result_box[1] = exc
                                            finally:
                                                _sync_done.set()

                                        _sync_thread = threading.Thread(target=_run_jira_sync, daemon=True)
                                        _sync_thread.start()

                                        # Show live scrolling log while the thread runs
                                        while not _sync_done.is_set():
                                            w, h = console.size
                                            viewport_h = max(3, h - 12)
                                            visible_log = _sync_log[-viewport_h:] if _sync_log else []
                                            cur = _sync_counter[0]
                                            tot = _sync_counter[1]
                                            counter = f"[{cur}/{tot}]" if tot else ""
                                            active = f"  ▸ {counter} {_sync_current[0]}"
                                            display_lines = "\n".join([*visible_log, active])
                                            live.update(
                                                _build_project_export_success_screen(
                                                    display_lines,
                                                    width=w,
                                                    height=h,
                                                    subtitle=f"{_tracker_label} sync",
                                                    hint="",
                                                )
                                            )
                                            time.sleep(_FRAME_TIME)
                                        _sync_thread.join()

                                        if _sync_result_box[1] is not None:
                                            from yeaboi.ui.session._utils import _classify_api_error

                                            _sync_err = _classify_api_error(_sync_result_box[1])
                                            path = f"{_tracker_label} sync failed: {_sync_err}"
                                        elif _sync_result_box[0] is not None:
                                            sr = _sync_result_box[0]
                                            new_gs = _sync_state_box[0]
                                            if new_gs:
                                                save_graph_state(project.id, new_gs)
                                                save_project_snapshot(project.id, new_gs)
                                            _iters = getattr(sr, "sprints_created", None) or getattr(
                                                sr, "iterations_created", {}
                                            )
                                            created = len(sr.stories_created) + len(sr.tasks_created) + len(_iters)
                                            skipped = sr.skipped
                                            errors = len(sr.errors)
                                            parts = []
                                            if created:
                                                parts.append(f"{created} created")
                                            if skipped:
                                                parts.append(f"{skipped} skipped")
                                            if errors:
                                                parts.append(f"{errors} errors")
                                            epic = getattr(sr, "epic_key", None) or getattr(sr, "epic_id", None) or ""
                                            prefix = f"Epic: {epic} — " if epic else ""
                                            summary = ", ".join(parts) or "Nothing to sync"
                                            # Show first error for diagnosis
                                            if sr.errors:
                                                first_err = sr.errors[0][:80]
                                                summary += f"\n{first_err}"
                                                # Write all errors to log file for debugging
                                                _err_path = Path.home() / ".scrum-agent" / "jira-sync-errors.log"
                                                _err_path.write_text("\n".join(sr.errors), encoding="utf-8")
                                            path = prefix + summary

                            if path:
                                w, h = console.size
                                live.update(
                                    _build_project_export_success_screen(
                                        str(path),
                                        width=w,
                                        height=h,
                                    )
                                )
                                # Show for at least 1.5s, then wait for a real keypress
                                _export_t0 = time.monotonic()
                                while True:
                                    k = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                                    elapsed = time.monotonic() - _export_t0
                                    if elapsed < 1.5:
                                        continue  # enforce minimum display time
                                    if k and k not in ("scroll_up", "scroll_down", ""):
                                        break

                            # Close submenu after export
                            export_submenu_open = False
                            submenu_visible_target = 0.0
                            submenu_html_fade = 0.0
                            submenu_md_fade = 0.0
                            submenu_jira_fade = 0.0
                            submenu_azdevops_fade = 0.0
                            submenu_html_fade_target = 0.0
                            submenu_md_fade_target = 0.0
                            submenu_jira_fade_target = 0.0
                            submenu_azdevops_fade_target = 0.0
                            exp_fade_target = 1.0  # restore Export highlight
                        elif key in ("esc", "q"):
                            export_submenu_open = False
                            submenu_visible_target = 0.0
                            submenu_html_fade_target = 0.0
                            submenu_md_fade_target = 0.0
                            submenu_jira_fade_target = 0.0
                            submenu_azdevops_fade_target = 0.0
                            exp_fade_target = 1.0  # restore Export highlight

                    # ── Team analysis popup mode ──────────────────────────────
                    # Button selector: Left/Right navigates, Enter confirms.
                    # When both boards configured: [Jira] [AzDO] [Skip] (3 buttons)
                    # When one board configured:   [Yes, Analyse] [Skip] (2 buttons)
                    elif team_popup_open:
                        _both_boards = _jira_ok and _azdevops_ok
                        _popup_btn_count = 3 if _both_boards else 2
                        if key == "left":
                            team_popup_sel = max(0, team_popup_sel - 1)
                        elif key == "right":
                            team_popup_sel = min(_popup_btn_count - 1, team_popup_sel + 1)
                        elif key == "enter":
                            if _both_boards:
                                # 0=Jira, 1=AzDO, 2=Skip
                                if team_popup_sel == 0:
                                    _team_popup_result = "analyse_jira"
                                elif team_popup_sel == 1:
                                    _team_popup_result = "analyse_azdevops"
                                else:
                                    _team_popup_result = "skip"
                            else:
                                # 0=Yes, 1=Skip
                                _team_popup_result = "analyse" if team_popup_sel == 0 else "skip"
                            team_popup_target = 0.0  # slide out
                        elif key in ("esc", "q"):
                            _team_popup_result = "skip"
                            team_popup_target = 0.0

                    # ── Delete popup mode ─────────────────────────────────────
                    # When the popup is open, Enter confirms delete, Esc dismisses.
                    # All other keys are ignored so the user can't navigate away.
                    elif delete_popup_open:
                        if key == "enter":
                            # Confirm delete — white flash, THEN slide down.
                            # Setting flash to 1.0 triggers the flash phase.
                            # The slide-down only begins once the flash decays
                            # below a threshold (see animation section below).
                            delete_popup_flash = 1.0
                            _delete_pending = True
                        elif key in ("esc", "q"):
                            # Dismiss popup without deleting
                            delete_popup_target = 0.0

                    # ── Normal project list mode ───────────────────────────────
                    elif key in ("up", "scroll_up", "down", "scroll_down"):
                        # Coalesce a fast wheel/held-key burst into one net move.
                        _delta = coalesce_steps(key, read_key, down=("down", "scroll_down"), up=("up", "scroll_up"))
                        if not _delta:
                            continue
                        proj_selected = (proj_selected + _delta) % proj_n
                        focus = 0
                        del_fade_target = 0.0
                        exp_fade_target = 0.0
                        card_fade = 0.0
                        card_fade_target = 1.0
                        action_btns_visible = 0.0
                        action_btns_visible_target = 2.0 if _is_project_row() else 0.0
                    elif key == "left":
                        if focus > 0:
                            focus -= 1
                        else:
                            proj_selected = (proj_selected - 1) % proj_n
                            focus = 0
                            card_fade = 0.0
                            card_fade_target = 1.0
                            action_btns_visible = 0.0
                            action_btns_visible_target = 2.0 if _is_project_row() else 0.0
                        del_fade_target = 1.0 if focus == 1 else 0.0
                        exp_fade_target = 1.0 if focus == 2 else 0.0
                    elif key == "right":
                        if _is_project_row() and focus < 2:
                            focus += 1
                        else:
                            proj_selected = (proj_selected + 1) % proj_n
                            focus = 0
                            card_fade = 0.0
                            card_fade_target = 1.0
                            action_btns_visible = 0.0
                            action_btns_visible_target = 2.0 if _is_project_row() else 0.0
                        del_fade_target = 1.0 if focus == 1 else 0.0
                        exp_fade_target = 1.0 if focus == 2 else 0.0

                    elif key == "enter":
                        # ── Focus 1: Delete → open popup overlay ───────────
                        if focus == 1 and _is_project_row():
                            delete_popup_open = True
                            delete_popup_target = 1.0
                            delete_popup_name = projects[proj_selected].name

                        # ── Focus 2: Export → open submenu ────────────────
                        elif focus == 2 and _is_project_row():
                            export_submenu_open = True
                            submenu_sel = 0  # default to HTML
                            submenu_visible_target = float(_submenu_max + 1)  # stagger-reveal all buttons
                            submenu_html_fade_target = 1.0
                            submenu_md_fade_target = 0.0
                            exp_fade_target = 0.0  # grey out Export while submenu is active

                        # ── Focus 0: Card (empty state / new project) ────
                        elif not projects or proj_selected == len(projects):
                            # Check freshness — show popup only if stale (>30d) or missing
                            _profile_fresh = _staleness_days is not None and _staleness_days <= 30
                            if _board_configured and not team_popup_open and not _profile_fresh:
                                # Build dynamic staleness message
                                if _staleness_days is not None:
                                    _team_popup_msg = (
                                        f"Your team analysis is {_staleness_days} days old. Re-analyse before planning?"
                                    )
                                else:
                                    _team_popup_msg = "No team analysis found. Analyse your board before planning?"
                                team_popup_open = True
                                team_popup_target = 1.0
                                team_popup_sel = 0
                                team_popup_pulse = 0.0
                                _team_popup_result = ""
                            else:
                                pulse = 1.0
                                break  # → intake mode selection
                        else:
                            # White pulse flash on selected card before opening
                            pulse = 1.0
                            _pulse_frames = 8
                            for _pf in range(_pulse_frames):
                                pulse = max(0.0, 1.0 - (_pf + 1) / _pulse_frames)
                                w, h = console.size
                                live.update(
                                    _build_project_list_screen(
                                        projects,
                                        proj_selected,
                                        width=w,
                                        height=h,
                                        focus=focus,
                                        del_fade=del_fade,
                                        exp_fade=exp_fade,
                                        card_fade=card_fade,
                                        pulse=pulse,
                                        jira_enabled=_jira_ok,
                                        azdevops_enabled=_azdevops_ok,
                                    )
                                )
                                time.sleep(_FRAME_TIME)

                            # Resume an existing project — load its saved graph state
                            # so the session can skip already-completed phases.
                            # See README: "Memory & State" — session persistence.
                            from langchain_core.messages import HumanMessage

                            from yeaboi.persistence import load_graph_state
                            from yeaboi.ui.session import run_session

                            project = projects[proj_selected]
                            saved_state = load_graph_state(project.id)

                            # Fallback: if no state file exists (project created before
                            # state persistence was added), build a minimal graph state
                            # from project metadata so the session skips Phase A.
                            if saved_state is None:
                                saved_state = {
                                    "messages": [HumanMessage(content=project.name)],
                                }

                            run_session(
                                live,
                                console,
                                intake_mode=saved_state.get("_intake_mode", "smart"),
                                resume_project_id=project.id,
                                resume_graph_state=saved_state,
                                dry_run=dry_run,
                                _read_key_fn=_read_key_fn,
                            )
                            # Session ended (Esc or completed) — return to project list
                            projects = _load_projects()
                            proj_n = len(projects) + 1
                            proj_selected = min(proj_selected, proj_n - 1)
                            pulse = 0.0
                            continue

                    elif key == "esc":
                        # ── Reverse transition: fade out cards → slide title down ──
                        # 1) cards fade out, 2) Planning slides from top to its
                        # position in the 3-item layout, 3) other titles fade in
                        # as Planning reaches its resting position.

                        # Step 1: Reverse stagger — cards disappear bottom-to-top
                        _dismiss_target = 0.0
                        _dismiss_visible = float(proj_n)
                        _dismiss_speed = 15.0  # cards per second (matches reveal)
                        _dismiss_start = time.monotonic()
                        while _dismiss_visible > _dismiss_target:
                            dt_d = time.monotonic() - _dismiss_start
                            _dismiss_visible = max(_dismiss_target, float(proj_n) - dt_d * _dismiss_speed)
                            w, h = console.size
                            live.update(
                                _build_project_list_screen(
                                    projects,
                                    proj_selected,
                                    width=w,
                                    height=h,
                                    cards_visible=_dismiss_visible,
                                    jira_enabled=_jira_ok,
                                    azdevops_enabled=_azdevops_ok,
                                )
                            )
                            time.sleep(_FRAME_TIME)

                        # Step 2: Slide Planning title from top down to its 3-item
                        # layout position. In the last ~40% of the slide, fade in
                        # the other two mode titles so they appear as Planning lands.
                        chosen = _MODE_CARDS[selected]
                        base_r, base_g, base_b = COLOR_RGB.get(chosen["color"], (180, 180, 180))
                        base_style = f"bold rgb({base_r},{base_g},{base_b})"
                        others = [i for i in range(n) if i != selected]

                        w, h = console.size
                        inner_h = h - 4
                        # Target: where Planning sits in the full 3-item mode screen.
                        # body_h for 3 items with Planning selected (no desc during slide):
                        # Planning(2) + blank(1) + CodeReview(2) + blank(1) + Sprint(2) = 8
                        body_h_no_desc = 2 * n + (n - 1)
                        target_offset = max(0, (inner_h - body_h_no_desc) // 2)
                        start_offset = 1  # current position (top of project list)

                        slide_frames = 18
                        for frame in range(slide_frames + 1):
                            t = frame / slide_frames
                            eased = ease_out_cubic(t)
                            current_offset = int(start_offset + (target_offset - start_offset) * eased)

                            # Fade others in during the last 40% of the slide
                            fade_t = max(0.0, (t - 0.6) / 0.4)

                            w, h = console.size
                            if fade_t <= 0:
                                # Only Planning visible — use slide frame
                                live.update(
                                    _build_slide_frame(
                                        chosen,
                                        top_offset=current_offset,
                                        width=w,
                                        height=h,
                                        style=base_style,
                                    )
                                )
                            else:
                                # Cross-fade: show all items, fade others from dark
                                # to their resting dim colour (100,100,100).
                                from yeaboi.ui.shared._animations import BLACK_RGB, lerp_color

                                dim_rgb = (100, 100, 100)
                                fade_rgb = lerp_color(fade_t, BLACK_RGB, dim_rgb)
                                live.update(
                                    _build_mode_screen(
                                        selected,
                                        width=w,
                                        height=h,
                                        shimmer_tick=0.0,
                                        desc_reveal=0,
                                        fade_style=fade_rgb,
                                        fade_indices=others,
                                    )
                                )
                            time.sleep(_FRAME_TIME)

                        # Step 3: Restart mode selection, skip the fade-in.
                        # Description typewriter starts fresh from select_time.
                        _restart_mode_select = True
                        _skip_fade_in = True
                        break  # break Phase 3 loop → restart Phase 1

                    # Animate button fade — smoothly move current values toward targets
                    now = time.monotonic()
                    dt = now - prev_tick
                    prev_tick = now
                    step = fade_speed * dt

                    if del_fade < del_fade_target:
                        del_fade = min(del_fade + step, del_fade_target)
                    elif del_fade > del_fade_target:
                        del_fade = max(del_fade - step, del_fade_target)
                    if exp_fade < exp_fade_target:
                        exp_fade = min(exp_fade + step, exp_fade_target)
                    elif exp_fade > exp_fade_target:
                        exp_fade = max(exp_fade - step, exp_fade_target)
                    if card_fade < card_fade_target:
                        card_fade = min(card_fade + step, card_fade_target)
                    elif card_fade > card_fade_target:
                        card_fade = max(card_fade - step, card_fade_target)
                    # Pulse decays toward 0
                    if pulse > 0:
                        pulse = max(0.0, pulse - step)

                    # Action buttons stagger animation (same speed as export submenu)
                    action_stagger_step = dt * 12.0
                    if action_btns_visible < action_btns_visible_target:
                        action_btns_visible = min(action_btns_visible + action_stagger_step, action_btns_visible_target)
                    elif action_btns_visible > action_btns_visible_target:
                        action_btns_visible = max(action_btns_visible - action_stagger_step, action_btns_visible_target)

                    # Export submenu stagger animation — faster rate so the
                    # three buttons pop in/out quickly one after another.
                    stagger_step = dt * 12.0  # ~0.25s to reveal all 3 buttons
                    if submenu_visible < submenu_visible_target:
                        submenu_visible = min(submenu_visible + stagger_step, submenu_visible_target)
                    elif submenu_visible > submenu_visible_target:
                        submenu_visible = max(submenu_visible - stagger_step, submenu_visible_target)
                    if submenu_html_fade < submenu_html_fade_target:
                        submenu_html_fade = min(submenu_html_fade + step, submenu_html_fade_target)
                    elif submenu_html_fade > submenu_html_fade_target:
                        submenu_html_fade = max(submenu_html_fade - step, submenu_html_fade_target)
                    if submenu_md_fade < submenu_md_fade_target:
                        submenu_md_fade = min(submenu_md_fade + step, submenu_md_fade_target)
                    elif submenu_md_fade > submenu_md_fade_target:
                        submenu_md_fade = max(submenu_md_fade - step, submenu_md_fade_target)
                    if submenu_jira_fade < submenu_jira_fade_target:
                        submenu_jira_fade = min(submenu_jira_fade + step, submenu_jira_fade_target)
                    elif submenu_jira_fade > submenu_jira_fade_target:
                        submenu_jira_fade = max(submenu_jira_fade - step, submenu_jira_fade_target)
                    if submenu_azdevops_fade < submenu_azdevops_fade_target:
                        submenu_azdevops_fade = min(submenu_azdevops_fade + step, submenu_azdevops_fade_target)
                    elif submenu_azdevops_fade > submenu_azdevops_fade_target:
                        submenu_azdevops_fade = max(submenu_azdevops_fade - step, submenu_azdevops_fade_target)

                    # Team analysis popup slide animation
                    if team_popup_t < team_popup_target:
                        team_popup_t = min(team_popup_t + step, team_popup_target)
                    elif team_popup_t > team_popup_target:
                        team_popup_t = max(team_popup_t - step, team_popup_target)

                    if team_popup_open and team_popup_t > 0:
                        team_popup_pulse += dt
                    elif team_popup_t <= 0:
                        team_popup_pulse = 0.0

                    # When team popup finishes sliding out, resolve the result.
                    if team_popup_open and team_popup_target == 0.0 and team_popup_t <= 0:
                        team_popup_open = False
                        if _team_popup_result.startswith("analyse"):
                            break
                        # "skip" falls through to normal intake
                        pulse = 1.0
                        break  # → intake mode selection

                    # Delete popup slide animation
                    if delete_popup_t < delete_popup_target:
                        delete_popup_t = min(delete_popup_t + step, delete_popup_target)
                    elif delete_popup_t > delete_popup_target:
                        delete_popup_t = max(delete_popup_t - step, delete_popup_target)

                    # Pulse clock: ticks whenever the popup is visible so the
                    # border oscillates between dark/bright red (like a loader).
                    if delete_popup_open and delete_popup_t > 0:
                        delete_popup_pulse += dt
                    elif delete_popup_t <= 0:
                        delete_popup_pulse = 0.0

                    # White flash decays toward 0 (slower rate so it's visible)
                    if delete_popup_flash > 0:
                        delete_popup_flash = max(0.0, delete_popup_flash - dt * 3.0)
                        # Once flash finishes, start the slide-down
                        if delete_popup_flash <= 0 and _delete_pending:
                            delete_popup_target = 0.0

                    # When popup finishes sliding out, clear the open state.
                    # If a delete was confirmed (_delete_pending), perform it now.
                    if delete_popup_open and delete_popup_target == 0.0 and delete_popup_t <= 0:
                        if _delete_pending:
                            from yeaboi.persistence import delete_project

                            project = projects[proj_selected]
                            delete_project(project.id)
                            projects = _load_projects()
                            if projects:
                                proj_n = len(projects) + 1
                                proj_selected = min(proj_selected, proj_n - 1)
                            else:
                                proj_n = 2
                                proj_selected = 0
                            _delete_pending = False
                            focus = 0
                            # Reset button animations so focus returns to card
                            del_fade = 0.0
                            del_fade_target = 0.0
                            exp_fade = 0.0
                            exp_fade_target = 0.0
                            action_btns_visible = 0.0
                            action_btns_visible_target = 2.0 if _is_project_row() else 0.0
                        else:
                            # Esc dismiss — keep Delete button focused
                            focus = 1
                            del_fade = 1.0
                            del_fade_target = 1.0
                            exp_fade = 0.0
                            exp_fade_target = 0.0
                        delete_popup_open = False
                        delete_popup_name = ""
                        delete_popup_flash = 0.0
                        card_fade = 1.0
                        card_fade_target = 1.0

                    w, h = console.size
                    live.update(
                        _build_project_list_screen(
                            projects,
                            proj_selected,
                            width=w,
                            height=h,
                            focus=focus,
                            del_fade=del_fade,
                            exp_fade=exp_fade,
                            card_fade=card_fade,
                            pulse=pulse,
                            action_btns_visible=action_btns_visible,
                            show_export_submenu=export_submenu_open or submenu_visible > 0,
                            submenu_sel=submenu_sel,
                            submenu_html_fade=submenu_html_fade,
                            submenu_md_fade=submenu_md_fade,
                            submenu_jira_fade=submenu_jira_fade,
                            submenu_azdevops_fade=submenu_azdevops_fade,
                            submenu_visible=submenu_visible,
                            delete_popup_name=delete_popup_name,
                            delete_popup_t=delete_popup_t,
                            delete_popup_pulse=delete_popup_pulse,
                            delete_popup_flash=delete_popup_flash,
                            team_popup_t=team_popup_t,
                            team_popup_sel=team_popup_sel,
                            team_popup_pulse=team_popup_pulse,
                            team_popup_message=_team_popup_msg,
                            jira_enabled=_jira_ok,
                            azdevops_enabled=_azdevops_ok,
                            shimmer_tick=now - _list_anim0,
                        )
                    )

                # Guard: Esc from project list sets _restart_mode_select → skip to outer loop
                if _restart_mode_select:
                    break

                # ── Phase 3a: Team analysis (if user selected "Analyse") ──────────
                if _team_popup_result.startswith("analyse"):
                    import threading

                    from yeaboi.team_profile import TeamProfileStore
                    from yeaboi.tools.team_learning import (
                        _fetch_azdevops_history,
                        _fetch_jira_history,
                        _run_parallel_analysis,
                    )

                    # Determine source from popup result
                    if _team_popup_result == "analyse_jira":
                        _ta_source = "jira"
                    elif _team_popup_result == "analyse_azdevops":
                        _ta_source = "azdevops"
                    else:
                        _ta_source = "jira" if _jira_ok else "azdevops"
                    _ta_project_key = ""
                    _ta_team_name = ""
                    try:
                        if _ta_source == "jira":
                            from yeaboi.config import get_jira_project_key

                            _ta_project_key = get_jira_project_key() or ""
                        else:
                            from yeaboi.config import (
                                get_azure_devops_project,
                                get_azure_devops_team,
                            )

                            _ta_project_key = get_azure_devops_project() or ""
                            _ta_team_name = get_azure_devops_team() or ""
                    except Exception:
                        pass

                    _ta_progress: list[str] = ["Fetching sprint history\u2026"]
                    _ta_profile_box: list = [None]
                    _ta_examples_box: list = [None]
                    _ta_sprint_names_box: list = [[]]
                    _ta_error_box: list[str] = [""]
                    _ta_done = threading.Event()

                    def _run_team_analysis():
                        try:
                            if _ta_source == "jira":
                                sprint_data = _fetch_jira_history(_ta_project_key, 8)
                            else:
                                sprint_data = _fetch_azdevops_history(_ta_project_key, 8)
                            if not sprint_data:
                                _ta_error_box[0] = "No closed sprints found."
                            else:
                                _ta_sprint_names_box[0] = [sd.get("sprint_name", "") for sd in sprint_data]
                                _result = _run_parallel_analysis(
                                    _ta_source, _ta_project_key or "unknown", sprint_data, _ta_progress
                                )
                                _ta_profile_box[0] = _result[0]
                                _ta_examples_box[0] = _result[1]
                        except Exception as exc:
                            from yeaboi.ui.session._utils import _classify_api_error

                            _ta_error_box[0] = _classify_api_error(exc)
                        finally:
                            _ta_done.set()

                    logger.info(
                        "Starting team analysis: source=%s, project=%s",
                        _ta_source,
                        _ta_project_key,
                    )
                    _ta_thread_start = time.monotonic()
                    _ta_thread = threading.Thread(target=_run_team_analysis, daemon=True)
                    _ta_thread.start()

                    # Processing animation while waiting
                    from yeaboi.ui.mode_select.screens._screens_secondary import (
                        _build_analysis_progress_screen,
                    )

                    _ta_anim_tick = 0.0
                    while not _ta_done.is_set():
                        _ta_anim_tick += _FRAME_TIME
                        w, h = console.size
                        live.update(
                            _build_analysis_progress_screen(
                                _ta_progress,
                                width=w,
                                height=h,
                                elapsed=time.monotonic() - _ta_thread_start,
                                anim_tick=_ta_anim_tick,
                                source=_ta_source,
                                mode="analysis",
                            )
                        )
                        time.sleep(_FRAME_TIME)
                    _ta_thread.join()

                    _ta_profile = _ta_profile_box[0]
                    _ta_duration = time.monotonic() - _ta_thread_start
                    if _ta_profile:
                        logger.info(
                            "Analysis complete: %s — %d sprints, %d stories (%.1fs)",
                            _ta_profile.team_id,
                            _ta_profile.sample_sprints,
                            _ta_profile.sample_stories,
                            _ta_duration,
                        )

                        # Attach AzDO team name to profile before saving
                        if _ta_team_name and not _ta_profile.team_name:
                            from dataclasses import replace as _dc_replace

                            _ta_profile = _dc_replace(_ta_profile, team_name=_ta_team_name)

                        # Save the fresh profile to the same DB every list/resume path
                        # reads from (_ana_dbp = ~/.yeaboi/data/sessions.db) so it's
                        # visible immediately, not only after a restart.
                        with TeamProfileStore(_ana_dbp) as store:
                            store.save(_ta_profile, examples=_ta_examples_box[0])
                        logger.info("Profile saved to %s", _ana_dbp)

                        # Write structured analysis log to ~/.scrum-agent/logs/
                        try:
                            from yeaboi.team_profile_exporter import write_analysis_log

                            _log_path = write_analysis_log(
                                _ta_profile,
                                examples=_ta_examples_box[0],
                                sprint_names=_ta_sprint_names_box[0],
                                duration_secs=_ta_duration,
                            )
                            logger.info("Analysis log: %s", _log_path)
                        except Exception as _log_exc:
                            logger.warning("Failed to write analysis log: %s", _log_exc)

                        # Show results screen (overview + section cards).
                        # Continue and Esc both fall through to intake below.
                        _ta_examples = _ta_examples_box[0] or {}
                        _ta_sprint_names = _ta_sprint_names_box[0]
                        _run_team_analysis_results(
                            live,
                            console,
                            read_key,
                            _FRAME_TIME,
                            _supports_timeout,
                            _ta_profile,
                            _ta_examples,
                            sprint_names=_ta_sprint_names,
                            team_name=_ta_team_name,
                        )
                    elif _ta_error_box[0]:
                        w, h = console.size
                        live.update(
                            _build_project_export_success_screen(
                                _ta_error_box[0],
                                width=w,
                                height=h,
                                subtitle="Analysis failed",
                                hint="Press any key to continue.",
                            )
                        )
                        while True:
                            k = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                            if k:
                                break

                # ── Phase 3b: Transition to intake mode selection ─────────────────
                # Show title + new subtitle, then stagger-reveal intake options.
                intake_selected = 0
                intake_n = len(_INTAKE_CARDS)
                intake_start = time.monotonic()

                # Blank frame — title + subtitle, no intake items yet
                w, h = console.size
                live.update(
                    _build_intake_screen(
                        intake_selected,
                        width=w,
                        height=h,
                        visible_items=0,
                    )
                )
                time.sleep(_FRAME_TIME * 2)

                # Stagger-reveal intake options one at a time
                for item_i in range(1, intake_n + 1):
                    w, h = console.size
                    live.update(
                        _build_intake_screen(
                            intake_selected,
                            width=w,
                            height=h,
                            visible_items=item_i,
                        )
                    )
                    time.sleep(_FRAME_TIME * 2)

                # ── Phase 4: Intake mode selection ────────────────────────────────
                chosen_intake = None
                while True:
                    key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()

                    if key in ("up", "left", "scroll_up", "down", "right", "scroll_down"):
                        _delta = coalesce_steps(
                            key,
                            read_key,
                            down=("down", "right", "scroll_down"),
                            up=("up", "left", "scroll_up"),
                        )
                        if not _delta:
                            continue
                        intake_selected = (intake_selected + _delta) % intake_n
                        intake_start = time.monotonic()
                    elif key == "enter":
                        chosen_intake = _INTAKE_CARDS[intake_selected]["key"]
                        if chosen_intake != "offline":
                            # ── Profile picker: let user select analysis profile ──
                            _selected_profile_id = ""
                            if _board_configured:
                                try:
                                    from yeaboi.team_profile import TeamProfileStore

                                    _pp_db = _ana_dbp
                                    if _pp_db.exists():
                                        with TeamProfileStore(_pp_db) as _pp_store:
                                            _pp_profiles = _pp_store.list_profiles()
                                        if _pp_profiles:
                                            from yeaboi.ui.mode_select.screens._screens_secondary import (
                                                _build_profile_picker_screen,
                                            )

                                            _pp_sel = 0
                                            _pp_n = len(_pp_profiles) + 1  # profiles + Skip
                                            w, h = console.size
                                            live.update(
                                                _build_profile_picker_screen(
                                                    _pp_profiles,
                                                    _pp_sel,
                                                    width=w,
                                                    height=h,
                                                )
                                            )
                                            while True:
                                                pk = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                                                if pk in ("up", "scroll_up"):
                                                    _pp_sel = (_pp_sel - 1) % _pp_n
                                                elif pk in ("down", "scroll_down"):
                                                    _pp_sel = (_pp_sel + 1) % _pp_n
                                                elif pk == "enter":
                                                    if _pp_sel < len(_pp_profiles):
                                                        _selected_profile_id = _pp_profiles[_pp_sel].team_id
                                                        logger.info(
                                                            "Profile selected: %s",
                                                            _selected_profile_id,
                                                        )
                                                    else:
                                                        logger.info("Profile picker: Skip selected")
                                                    break
                                                elif pk in ("esc", "q"):
                                                    break
                                                w, h = console.size
                                                live.update(
                                                    _build_profile_picker_screen(
                                                        _pp_profiles,
                                                        _pp_sel,
                                                        width=w,
                                                        height=h,
                                                    )
                                                )
                                except Exception:
                                    logger.debug("Profile picker failed", exc_info=True)

                            from yeaboi.ui.session import run_session

                            run_session(
                                live,
                                console,
                                intake_mode=chosen_intake,
                                dry_run=dry_run,
                                _read_key_fn=_read_key_fn,
                                analysis_profile_id=_selected_profile_id,
                            )
                            # Session ended (Esc or completed) — return to project list
                            projects = _load_projects()
                            proj_n = len(projects) + 1
                            proj_selected = min(proj_selected, proj_n - 1)
                            _restart_project_list = True
                            break  # break Phase 4 loop → restart Phase 3
                        break  # → offline sub-menu (Phase 5)
                    elif key == "esc":
                        # Back to project list
                        _restart_project_list = True
                        break

                    elapsed = time.monotonic() - intake_start
                    reveal = elapsed * _DESC_SCROLL_SPEED  # float for sub-char fade

                    w, h = console.size
                    tick = time.monotonic() - start_time
                    live.update(
                        _build_intake_screen(
                            intake_selected,
                            width=w,
                            height=h,
                            shimmer_tick=tick,
                            desc_reveal=reveal,
                        )
                    )

                # Guard: Phase 4 Esc or session-end sets restart → skip Phase 5
                if _restart_project_list:
                    continue
                if _restart_mode_select:
                    break

                # ── Phase 5: Offline sub-menu (Export / Import) ───────────────
                offline_selected = 0
                offline_n = len(_OFFLINE_CARDS)
                offline_start = time.monotonic()

                # Blank frame — title + subtitle, no items yet
                w, h = console.size
                live.update(
                    _build_offline_screen(
                        offline_selected,
                        width=w,
                        height=h,
                        visible_items=0,
                    )
                )
                time.sleep(_FRAME_TIME * 2)

                # Stagger-reveal offline options one at a time
                for item_i in range(1, offline_n + 1):
                    w, h = console.size
                    live.update(
                        _build_offline_screen(
                            offline_selected,
                            width=w,
                            height=h,
                            visible_items=item_i,
                        )
                    )
                    time.sleep(_FRAME_TIME * 2)

                # Phase 5 interaction loop
                while True:
                    key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()

                    if key in ("up", "left", "scroll_up", "down", "right", "scroll_down"):
                        _delta = coalesce_steps(
                            key,
                            read_key,
                            down=("down", "right", "scroll_down"),
                            up=("up", "left", "scroll_up"),
                        )
                        if not _delta:
                            continue
                        offline_selected = (offline_selected + _delta) % offline_n
                        offline_start = time.monotonic()
                    elif key == "enter":
                        break  # → Phase 5b (export or import)
                    elif key == "esc":
                        # Go back to project list
                        _restart_project_list = True
                        break

                    elapsed = time.monotonic() - offline_start
                    reveal = elapsed * _DESC_SCROLL_SPEED  # float for sub-char fade

                    w, h = console.size
                    tick = time.monotonic() - start_time
                    live.update(
                        _build_offline_screen(
                            offline_selected,
                            width=w,
                            height=h,
                            shimmer_tick=tick,
                            desc_reveal=reveal,
                        )
                    )

                # Guard: if Phase 5 Esc or Import Esc set restart, skip 5b
                if _restart_project_list:
                    continue

                # ── Phase 5b: Export or Import ────────────────────────────────
                offline_choice = _OFFLINE_CARDS[offline_selected]["key"]

                if offline_choice == "export":
                    # Export a blank questionnaire template directly
                    from yeaboi.questionnaire_io import export_questionnaire_md

                    out_path = export_questionnaire_md(None, Path("scrum-questionnaire.md"))
                    w, h = console.size
                    live.update(_build_export_success_screen(str(out_path), width=w, height=h))
                    # Wait for any keypress to exit
                    while True:
                        key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()
                        if key:
                            break
                    return None  # cli.py exits

                else:
                    # Import — show text input for file path
                    import_value = ""
                    import_error = ""
                    _default_path = "scrum-questionnaire.md"

                    w, h = console.size
                    live.update(_build_import_screen(import_value, width=w, height=h, placeholder=_default_path))

                    while True:
                        key = read_key(timeout=_FRAME_TIME) if _supports_timeout else read_key()

                        if key == "enter":
                            # Use default if empty
                            file_path = import_value.strip() if import_value.strip() else _default_path
                            p = Path(file_path)
                            if not p.exists():
                                import_error = f"File not found: {file_path}"
                            elif not p.suffix == ".md":
                                import_error = f"Expected a .md file, got: {p.suffix or 'no extension'}"
                            else:
                                return ("project-planning", None, str(p))

                            w, h = console.size
                            live.update(
                                _build_import_screen(
                                    import_value,
                                    width=w,
                                    height=h,
                                    error=import_error,
                                    placeholder=_default_path,
                                )
                            )
                            continue

                        elif key == "esc":
                            _restart_project_list = True
                            break
                        elif key == "backspace":
                            import_value = import_value[:-1]
                            import_error = ""
                        elif key == "clear":
                            import_value = ""
                            import_error = ""
                        elif key.startswith("paste:") if isinstance(key, str) else False:
                            import_value += key[6:]
                            import_error = ""
                        elif key == "ctrl+v":
                            # A file-path field never reaches an LLM — reject image paste.
                            from yeaboi.ui.shared._attachments import UNSUPPORTED_MESSAGE

                            import_error = UNSUPPORTED_MESSAGE
                        elif len(key) == 1 and key.isprintable():
                            import_value += key
                            import_error = ""
                        elif key == "":
                            pass  # timeout, no input
                        else:
                            continue

                        w, h = console.size
                        live.update(
                            _build_import_screen(
                                import_value,
                                width=w,
                                height=h,
                                error=import_error,
                                placeholder=_default_path,
                            )
                        )

    return None
