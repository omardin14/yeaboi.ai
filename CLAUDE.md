# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Terminal-based AI Scrum Master agent built with LangGraph, LangChain, and Anthropic Claude (with OpenAI, Google, and AWS Bedrock as alternative providers). Decomposes projects into epics, user stories, tasks, and sprint plans. Version 1.2.0. Deployed on AWS Lightsail via OpenClaw with Bedrock.

## Commands

```bash
make test                 # Unit + integration + contract tests (full suite, no API keys needed)
make test-fast            # Unit tests only (< 3s, tight edit-test loop)
make test-v               # Full suite verbose
make test-all             # Everything including golden evaluators
make lint                 # Lint with ruff
make format               # Format with ruff
make run                  # Run the CLI (ARGS="--flag" to pass arguments)
make run-dry              # Run TUI with fake delays, no LLM calls
make eval                 # Run golden dataset evaluators
make contract             # Run contract tests (recorded API responses)
make smoke-test           # Live API smoke tests (requires real credentials)
make snapshot-update      # Update syrupy snapshot baselines after formatter changes
make budget-report        # Show prompt token counts for trend monitoring
make graph                # Generate agent graph visualisation PNG
make build                # Build sdist + wheel into dist/
make publish              # Publish to PyPI
make record               # Re-record VCR cassettes against real APIs
make clean                # Remove build artifacts and caches
```

Run a single test: `uv run pytest tests/unit/test_state.py -v`
Run a single test class: `uv run pytest tests/unit/test_state.py::TestPriority -v`

### Recording terminal GIFs (for README)

```bash
brew install asciinema agg
asciinema rec docs/demo.cast -c "yeaboi --dry-run"   # record
agg docs/demo.cast docs/demo.gif --theme github-dark       # convert to GIF
rm docs/demo.cast                                           # clean up source
```

## Code Style

- Python 3.11+, ruff for linting/formatting (line-length 120)
- Imports sorted by ruff (isort rules: stdlib, third-party, local)
- Tests in `tests/`, source in `src/yeaboi/`

## REQUIRED: Learning-First Development

This is the developer's first AI agent. These are NOT optional — follow them on every implementation task.

1. **ALWAYS add `# See README: <section name>` comments** when introducing a LangGraph or LangChain concept for the first time in a file. Cross-reference the relevant README section so the developer can look up the theory.
2. **ALWAYS explain LangGraph/LangChain concepts in code comments** on first use — what a reducer does, why `add_messages` exists, what `StateGraph` expects, what `bind_tools` does, etc. Do NOT assume familiarity with these frameworks.
3. **ALWAYS explain architectural decisions** in your response — when choosing between approaches, state the trade-offs and why this approach was chosen.

Key README sections to reference:
- "Architecture" — four layers, three design principles, agent graph, TUI system
- "The ReAct Loop" — Thought → Action → Observation pattern
- "Agentic Blueprint Reference" — core graph setup, two core nodes, wiring, tools, memory, streaming
- "Prompt Construction" — ARC framework, few-shot, chain-of-thought, flipped prompt
- "Session Management" — SQLite persistence, --resume, session IDs
- "Guardrails" — input guardrails (4 layers), output guardrails (4 layers), human-in-the-loop
- "Tools" — 30 tools, tool types, risk levels
- "Scrum Standards" — story format, acceptance criteria, story points, DoD, discipline tagging

## REQUIRED: Progress Tracking

After completing any implementation step, IMMEDIATELY update `TODO.md`:
- Change `- [ ]` to `- [x]` for the completed item
- Do NOT wait for the developer to ask — do it automatically as part of the workflow

## REQUIRED: Verification

After every code change, ALWAYS run:
1. `make test` — all tests must pass
2. `make lint` — must be clean

Do NOT commit until both pass.

## REQUIRED: Observability & Test Coverage

Every new feature MUST include all three pillars before it can be considered complete:

### 1. Logging
- **Every user action** must have a `logger.info()` — entry, exit, key decisions, errors
- **Every LLM call** must log via `_llm_invoke()` (which calls `track_usage()` automatically)
- **Every external API call** (Jira, AzDO, GitHub) must log start + result
- **Every error path** must log at `warning` or `error` level with context
- Use `logger.debug()` for detailed data (response payloads, intermediate calculations)

### 2. Log Directory
- **New TUI pages** (Usage, Settings, etc.) use the appropriate log directory from `paths.py`
- **Analysis mode** logs go to `paths.ANALYSIS_LOGS_DIR` (~/.yeaboi/logs/analysis/)
- **Planning mode** session logs go to `paths.PLANNING_LOGS_DIR` (~/.yeaboi/logs/planning/)
- **TUI-level logs** go to `paths.TUI_LOGS_DIR` (~/.yeaboi/logs/tui/)
- **Exports** use `paths.get_analysis_export_dir()` or `paths.get_planning_export_dir()`
- All paths MUST come from `src/yeaboi/paths.py` — never hardcode `Path.home() / ".yeaboi"`

### 3. Tests
- **Every new function** gets at least one unit test (happy path + error case)
- **Every new screen builder** (`_build_*_screen`) gets render tests (returns Panel, handles empty data, scrollable)
- **Every LLM-dependent function** gets mock tests (successful response, error fallback, code fence handling)
- **Every new state field** gets serialization round-trip tests
- **Secret/sensitive data** rendering must be tested for proper masking
- Tests live in `tests/unit/` — one file per source module or grouped by feature

## REQUIRED: TUI Component Standards

All TUI screens MUST use the shared component system in `src/yeaboi/ui/shared/_components.py`. Do NOT duplicate rendering logic.

### Shared Primitives (use these, don't rewrite)
| Component | Function | Purpose |
|-----------|----------|---------|
| `Theme` | `ANALYSIS_THEME`, `PLANNING_THEME`, `USAGE_THEME`, `SETTINGS_THEME` | Colour palette per mode |
| Buttons | `build_action_buttons(actions, selected)` | Consistent button row (Accept/Edit/Export/Back etc.) |
| Scrollbar | `build_scrollbar(viewport_h, total, offset, max_scroll)` | Right-side scroll indicator |
| Progress | `build_progress_dots(stages, current, theme=)` | Stage indicator (● ● ○ ○ ○) |
| Viewport | `calc_viewport(height, header_h=, action_h=)` | Viewport height calculation |
| Titles | `planning_title()`, `analysis_title()`, `usage_title()`, `settings_title()` | ASCII art headers |
| Popup | `build_popup(message, width=, border_style=)` | Confirmation dialogs |
| Padding | `PAD` constant | Left indent for visual balance |

### Page Structure (every `_build_*_screen` function MUST follow)
```
Panel(height=height, padding=(1,2))
  ├── Text("")                    # blank
  ├── title                       # ASCII art from *_title()
  ├── Text("")                    # blank
  ├── subtitle / progress dots    # context line
  ├── Text("")                    # blank
  ├── viewport_renderable         # scrollable content (with optional scrollbar)
  ├── Text("")                    # blank
  ├── btn_top                     # from build_action_buttons()
  ├── btn_mid                     #
  └── btn_bot                     #
```

### Rules
1. **DRY** — Never inline button rendering, scrollbar math, or viewport calculations. Always use shared functions.
2. **Themes** — Never hardcode colour values (`"rgb(100,180,100)"`). Use `theme.accent`, `theme.muted`, etc. from the appropriate Theme constant.
3. **New pages** — Adding a new mode/page requires: a Theme constant, a `*_title()` function, a colour entry in `COLOR_RGB`, and an entry in `_MODE_CARDS` (if it's a main menu item).
4. **Consistency** — All pages use the same Panel structure (title → subtitle → viewport → buttons). No exceptions.
5. **Scrollbar** — Content that can overflow MUST use `build_scrollbar()`. Use `always_show=True` for pages where the track should always be visible.
6. **Buttons** — Register new button labels in `_BTN_COLORS` dict in `_components.py` with accent/grey colour tuples.
7. **No `_PAD` aliases** — Import `PAD` directly from `yeaboi.ui.shared._components`. Legacy `_PAD = PAD` aliases exist but should not be added to new files.

## Project Structure

```
src/yeaboi/
  __init__.py           — Version (__version__), LangSmith noise suppression
  cli.py                — CLI entry point (argparse, 20 flags, headless mode, session mgmt)
  config.py             — Environment/config (API keys, LangSmith, proxy detection)
  persistence.py        — Session persistence layer (checkpoint system)
  sessions.py           — SessionStore (SQLite), state serialization, schema versioning
  setup_wizard.py       — First-time setup flow (provider selection, API key validation)
  formatters.py         — Rich Table/Panel rendering (dark/light themes)
  html_exporter.py      — Export plans to self-contained HTML
  json_exporter.py      — Export plans to clean JSON (for CI/CD pipelines)
  markdown_convert.py   — Generated Markdown → Notion blocks / Confluence storage XHTML (pure, no SDK; nested lists, hard breaks, links, native Confluence task lists, ⚠ Notices → callout/warning panels, ![alt](path) images via caller-supplied upload maps)
  export_targets.py     — publish_to_notion/publish_to_confluence/publish_markdown (PublishResult; never raises); uploads referenced images (Notion File Upload API / Confluence attach_file), localize_images() for portable .md folders, and yeaboi branding (🤙 Notion page icon, `yeaboi` Confluence label, linked footer auto-appended); with no exports page configured, docs group under an auto-created "🤙 yeaboi" container page (find-or-create, session-cached, best-effort fallback to root/space root)
  charts.py             — velocity/delivered-work PNG charts for exports (optional `charts` extra = matplotlib, lazy-imported; every function returns None gracefully)
  jira_sync.py          — Batch Jira creation (idempotent, cascade, progress callbacks)
  azdevops_sync.py      — Batch Azure DevOps creation (idempotent, cascade, progress callbacks)
  questionnaire_io.py   — Import/export questionnaire templates as Markdown
  input_guardrails.py   — Input validation (length, injection, profanity, relevance)
  output_guardrails.py  — Output validation (story format, AC coverage, sprint capacity)
  agent/
    state.py            — ScrumState TypedDict, artifact dataclasses, enums
    graph.py            — Graph compilation and wiring (create_graph())
    nodes.py            — Node functions (intake, analyzer, generators, planner)
    llm.py              — LLM provider factory (Anthropic/OpenAI/Google/Bedrock, lazy imports)
  prompts/
    system.py           — Base system prompt (Scrum Master persona)
    intake.py           — 30 questions, smart/standard modes, adaptive templates, validation
    analyzer.py         — Project analysis prompt
    feature_generator.py— Feature generation prompt
    story_writer.py     — Story writing prompt with few-shot examples
    task_decomposer.py  — Task decomposition prompt
    sprint_planner.py   — Sprint planning prompt
    standup.py          — Daily Standup summary prompt (ARC framework)
  standup/              — Daily Standup mode (headless-capable, OS-scheduled)
    __init__.py         — public API (run_standup, StandupStore)
    engine.py           — run_standup() pipeline (collect → confidence → LLM summary → deliver → record)
    collector.py        — fan-out recent-activity collection across all sources (graceful skip)
    confidence.py       — deterministic sprint-day + burn-down confidence
    sprint_context.py   — sprint dates/points from plan state + live Jira/AzDO progress
    delivery.py         — NotificationDelivery ABC + Terminal/Desktop/Slack/Email + deliver()
    interactive.py      — timed, TTY-aware scheduled run (prompts for update + confirm; headless fallback)
    errors.py           — StandupSourceError (surfaces source 401/403 as warnings)
    scheduler.py        — OS-native scheduling (launchd on macOS, crontab on Linux); lead-time aware
    render.py           — StandupReport → plaintext (Slack/email) + Rich (terminal/TUI)
    export.py           — StandupReport → Markdown + self-contained HTML (auto-saved every run; Export button)
    store.py            — StandupStore (standup_config/history/updates tables, schema v6)
  retro/                — Retro mode (collaborative, LAN browser board)
    __init__.py         — public API (RetroBoard, RetroServer, RetroStore, board_to_report)
    board.py            — RetroBoard (threading.Lock-guarded live cards) + board_to_report()
    server.py           — RetroServer: stdlib ThreadingHTTPServer, token auth, LAN IP, share-code encode/decode
    page.py             — build_board_html(): self-contained dark browser page (4 grids, polling, XSS-safe)
    engine.py           — generate_action_items(): one LLM call (parse → fallback) from feedback cards
    tunnel.py           — optional Cloudflare quick tunnel (off-network joining); auto-downloads cloudflared, zero-setup
    export.py           — RetroReport → Markdown + self-contained HTML (Export button)
    store.py            — RetroStore (retro_history table, schema v7)
  performance/          — Performance mode (per-engineer 1:1 prep/completion + 6-month review)
    __init__.py         — public API (run_one_on_one_prep, complete_one_on_one, run_six_month_review, PerformanceStore, fetch_roster)
    roster.py           — fetch_roster(): engineer list from Jira/AzDO assignees (graceful [])
    activity.py         — gather_engineer_activity(): current+prior-sprint tickets for one engineer
    engine.py           — the 3 workflow pipelines (parse → fallback → format; one LLM call each)
    context.py          — gather_performance_context(): per-engineer signal → Planning/Analysis
    render.py           — Prep/Completion/Review → Rich + plaintext
    export.py           — Prep/Completion/Review → Markdown + HTML (paths.get_performance_export_dir)
    delivery.py         — 1:1 summary email via SMTP (reuses standup config.get_smtp_*)
    store.py            — PerformanceStore (one_on_ones/reviews/notes tables, schema v8)
    references/         — bundled default competency_framework.md (overridable via env)
  reporting/            — Reporting mode (business-friendly delivery report: last sprint / last month)
    __init__.py         — public API (run_delivery_report, ReportingStore, export_report, build_presentation_html)
    activity.py         — gather_delivered_work(): team-wide completed (Done/Closed) tickets over the period
    sprints.py          — quarter_bounds() + list_sprints() (tracker→plan fallback) for the quarter multi-select
    engine.py           — run_delivery_report() pipeline (gather → one LLM "design" call → parse → fallback)
    render.py           — DeliveryReport → Rich + plaintext (TUI detail view)
    export.py           — DeliveryReport → Markdown + HTML + slide deck (paths.get_reporting_export_dir)
    presentation.py     — build_presentation_html(): self-contained keyboard-nav slide deck (E501-exempt asset)
    store.py            — ReportingStore (reporting_history table, schema v9)
  tools/
    __init__.py         — get_tools() factory (lazy imports all tool modules)
    github.py           — GitHub repo/file/issues/readme (4 tools) + recent-activity helpers
    local_git.py        — local `git log` recent-commit reader (standup, no SDK/creds)
    azure_devops.py     — Azure DevOps repo/file/work items/board/velocity/create (9 tools)
    jira.py             — Jira board/velocity/sprint/epic/story (6 tools)
    confluence.py       — Confluence search/read/write (5 tools)
    notion.py           — Notion search/read/write (5 tools) + recent-pages helper (own token, not Atlassian auth)
    codebase.py         — Local repo scanning (3 tools)
    calendar_tools.py   — Bank holiday detection (1 tool)
    llm_tools.py        — LLM-powered estimation and AC generation (2 tools)
  repl/                 — Legacy REPL (used for CLI-flag-driven flows)
    __init__.py         — run_repl() entry point
    _intake_menu.py     — Intake mode selection
    _io.py              — Artifact rendering, file import/export, markdown export
    _mode_menu.py       — Mode selection menu
    _questionnaire.py   — Questionnaire UI (one-at-a-time flow)
    _review.py          — Review checkpoint UI (accept/edit/reject)
    _ui.py              — Pipeline progress, streaming, spinner, toolbar
  ui/                   — Full-screen TUI system
    splash.py           — Animated intro
    mode_select/        — Mode selection screens, project cards, project list
    provider_select/    — LLM/tool provider setup, verification
    session/            — Main session (phases, editor, pipeline, Jira export, dry-run)
    shared/             — Animations, ASCII font, components, mouse input
tests/
  unit/                 — Fast unit tests (one file per source module)
    nodes/              — Node tests split into ~9 files (analyzer, route, tasks, etc.)
  integration/          — Graph compilation, multi-node flows, CLI, REPL
  contract/             — Contract tests with recorded API responses (VCR cassettes)
  smoke/                — Live API smoke tests (requires credentials)
  golden/               — Golden dataset evaluators
  fixtures/             — Test data files (SCRUM.md, questionnaire-answers.md)
  _node_helpers.py      — Shared factory functions + JSON fixtures for node tests
```

Conventions:
- Agent logic lives in `agent/` — state, graph wiring, and node functions
- Prompts are separate from agent logic in `prompts/`
- Tools are separate in `tools/` — each tool gets a `@tool` decorator with a descriptive docstring
- Re-export public APIs from `__init__.py` (e.g. `from yeaboi.agent import ScrumState`)
- The `ui/` package is the full-screen TUI; `repl/` is the legacy REPL for CLI-flag-driven flows (`--quick`, `--full-intake`, `--questionnaire`, `--mode`)
- Files prefixed with `_` inside `repl/` and `ui/` subpackages are internal — not public API

## App Flow

Two paths:

1. **Interactive TUI**: `cli.py` → splash → mode selection TUI → provider selection → session TUI
2. **CLI-flag / headless**: `cli.py` → `run_repl()` (for `--quick`, `--full-intake`, `--questionnaire`, `--mode`) or `_run_headless()` (for `--non-interactive`)

Sessions can be listed (`--list-sessions`), resumed (`--resume`), and cleared (`--clear-sessions`). `--dry-run` runs the TUI with fake delays and no LLM calls. `--non-interactive` runs the full pipeline headlessly with `--description` as input and `--output {json,html,markdown}` for format.

## CLI Flags

Key flags to know about when modifying the CLI:

| Flag | Description |
|------|-------------|
| `--non-interactive` | Headless mode (requires `--description`) |
| `--description TEXT` | Project description; `@file.txt` reads from file |
| `--output {markdown,json,html}` | Output format (only with `--non-interactive` or `--export-only`) |
| `--team-size N` | Maps to intake Q6 |
| `--sprint-length {1,2,3,4}` | Maps to intake Q8 |
| `--quick` / `--full-intake` | Mutually exclusive intake modes |
| `--questionnaire PATH` | Import filled-in questionnaire |
| `--export-only` | Auto-accept all review checkpoints |
| `--resume [ID]` | Resume session (no arg = picker, `latest` = most recent) |
| `--theme {dark,light}` | Terminal colour theme |
| `--dry-run` | TUI with mock data, no LLM calls |
| `--setup` | Re-run first-time setup wizard |
| `--install-skill [DIR]` | Install bundled OpenClaw skill to `~/.openclaw/skills/` (or custom dir) |
| `--standup-run` | Headless: run a daily standup and deliver it (what the OS scheduler invokes) |
| `--standup-interactive` | With `--standup-run`: timed prompt for the user's update + confirm before generating (TTY-aware; headless fallback) |
| `--standup-session ID` | Session to run the standup for (default: most recent) |
| `--standup-output {terminal,desktop,slack,email,all}` | Override the session's saved delivery channels |

Validation rules in `main()`:
- `--non-interactive` requires `--description`
- `--output` requires `--non-interactive` or `--export-only`
- `--export-only` requires `--quick` or `--questionnaire`

## Node Conventions

Nodes are plain functions in `agent/nodes.py` taking `ScrumState` and returning a dict. Key patterns:

### Parse → Fallback → Format

Every generation node follows this three-helper pattern:
- `_parse_*_response(text)` — extract JSON from LLM response, handle markdown fences
- `_build_fallback_*()` — deterministic fallback artifacts when LLM fails (no LLM call)
- `_format_*()` — Rich rendering for REPL display

### Error handling

- `_is_llm_auth_or_billing_error(e)` checks if an exception is auth/billing — these are **re-raised** (user must fix credentials). All other LLM errors trigger **fallback artifacts** and a warning log.
- Rate-limit errors (429) are retried with exponential backoff in the REPL layer (`_handle_rate_limit`), not in nodes.

### Human-in-the-loop review

When a generation node produces output, it sets `pending_review` to the node name. The REPL intercepts the next user input and routes to `[1] Accept  [2] Edit  [3] Reject`. On edit, feedback is packed as `"{feedback}\n\n---PREVIOUS OUTPUT---\n{serialized}"` so the node can extract both the feedback and previous generation.

## Prompt Conventions

Prompts live in `prompts/` with a factory function per file:
- `get_system_prompt()`, `get_analyzer_prompt(questionnaire, ...)`, `get_feature_generator_prompt(analysis)`, etc.
- Each factory takes parameters (not the full state) and returns a string
- Prompts use the ARC framework: Ask (what to do), Requirements (constraints), Context (background)
- `# See README: "..."` comments cross-reference theory sections

## Tool Conventions

### Registration

All tools are registered via `get_tools()` in `tools/__init__.py`. This single factory function imports all tool modules and returns a flat list of `BaseTool` instances.

### Lazy imports

Tool modules are imported **inside** `get_tools()`, not at module level. This is because tool dependencies (PyGithub, azure-devops, jira SDK) may not be installed. Lazy import means `from yeaboi.tools import get_tools` always succeeds; ImportError surfaces only when `get_tools()` is called.

### Adding a new tool

1. Create or extend a file in `tools/` with `@tool`-decorated functions
2. Import and append to the tools list in `get_tools()`
3. The docstring is critical — the LLM reads it to decide when to use the tool
4. Set risk level via the tool's position in the graph routing (auto-execute for read, human confirmation for write)

## LLM Provider Conventions

`agent/llm.py` provides `get_llm()` — a factory supporting Anthropic (default), OpenAI, Google, and AWS Bedrock:
- Each provider is **lazy-imported** inside an if-branch so the module works even if optional packages aren't installed
- Provider selected via `LLM_PROVIDER` env var; model override via `LLM_MODEL`
- Default models: `claude-sonnet-4-20250514` (Anthropic), `gpt-4o` (OpenAI), `gemini-2.0-flash` (Google), `us.anthropic.claude-sonnet-4-20250514-v1:0` (Bedrock)
- Install optional providers: `uv sync --extra openai` / `--extra google` / `--extra bedrock`
- **Bedrock** uses IAM credentials (no API key) — auto-detects AWS profile from `~/.aws/config` via `get_aws_profile()` in `config.py`. On Lightsail, uses `[profile assumed]` with `credential_source=Ec2InstanceMetadata`. The boto3 session is created with explicit profile + increased read timeout (300s) for cross-region inference profiles.

## State Schema Conventions

- **ScrumState** is a `TypedDict` — this is the LangGraph convention for graph state
- `messages` is the only required field, using `Annotated[list[BaseMessage], add_messages]` for append semantics
- All other fields are optional (`total=False`) and populated progressively as nodes run
- **Frozen dataclasses** for artifacts (Feature, UserStory, Task, Sprint, ProjectAnalysis) — immutable once created, serializable via `asdict()`
- **Mutable dataclass** for QuestionnaireState — updated incrementally by the intake node
- Artifact lists use `Annotated[list[...], operator.add]` so nodes can return new items that get appended

### Adding new state fields

1. Add to `ScrumState` in `agent/state.py`
2. Add tests in `test_state.py`
3. Update `__init__.py` exports if public
4. If the field should persist across `--resume`, it serializes automatically (only `messages` is skipped)
5. If adding a field to a **frozen dataclass**, always provide a default value for backward compatibility with saved sessions (e.g., `title: str = ""`, `discipline: Discipline = Discipline.FULLSTACK`)

### Frozen dataclass backward compatibility

New fields on frozen dataclasses MUST have defaults so deserialization of old JSON doesn't fail:
```python
# Good — old sessions without this field still deserialize
title: str = ""
discipline: Discipline = Discipline.FULLSTACK
test_plan: str = ""

# Bad — breaks --resume for sessions saved before this field existed
title: str   # no default!
```

The `_dict_to_*()` functions in `sessions.py` use `.get()` for optional fields so missing keys don't raise KeyError.

## Session Persistence

### Serialization

`sessions.py` handles state serialization for `--resume`:
- `messages` is the only field skipped (not needed for resume; re-initialized to `[]`)
- Custom `_StateEncoder` handles: frozen dataclasses (`asdict()`), enums (`.value`), sets (→ lists), tuples (→ lists)
- Reconstruction functions: `_dict_to_analysis()`, `_dict_to_story()`, `_dict_to_task()`, `_dict_to_sprint()`, `_dict_to_questionnaire()` — each handles type conversion (enum parsing, tuple reconstruction)

### Schema versioning

- `CURRENT_SCHEMA_VERSION = 9` tracked in a `schema_info` table (v3=team_profiles, v4=session_mode, v5=token_usage, v6=standup config/history/updates, v7=retro history, v8=performance 1:1s/reviews/notes, v9=reporting history)
- On startup: if stored version > current → `schema_mismatch = True` (warn user); if stored version < current → run migrations
- Session IDs: internal `new-<8hex>-<YYYY-MM-DD>`, display `<project-slug>-<YYYY-MM-DD>`

## Testing Conventions

- One test file per source module: `repl.py` → `test_repl.py`, `state.py` → `test_state.py`
- Group related tests in classes: `TestGracefulExit`, `TestStreaming`, `TestPriority`
- Use `pytest` fixtures for shared setup (e.g. `_make_console()` for rich Console with StringIO buffer)
- Use `monkeypatch` to avoid filesystem writes, network calls, and delays in tests
- Test both happy path and edge cases (empty input, boundary values, immutability)
- Node tests live in `tests/unit/nodes/` — split into ~9 files by node (analyzer, route, tasks, etc.)
- Shared node test helpers in `tests/_node_helpers.py`: `make_completed_questionnaire()`, `make_dummy_analysis()`, `make_sample_features()`, `make_sample_stories()`, `make_sample_sprints()`
- **Never modify `tests/integration/test_repl.py`** — it monkeypatches 10+ names in `yeaboi.repl` and is the only test file with this level of coupling. Future tests should avoid this pattern.
- Pytest markers: `slow` (graph compilation), `eval` (golden evaluators), `vcr` (contract tests), `smoke` (live API)

## Logging

**All handler setup lives in `src/yeaboi/logging_setup.py`** — one shared format, one fallback level (`WARNING`), rotation everywhere (2 MB, 3 backups). Never build a `FileHandler` inline; use the central module:
- `configure_logging()` — attaches the always-on main log (`~/.yeaboi/logs/tui/yeaboi.log`); called once early in `cli.main()`
- `with mode_log("<mode>"):` — routes all records to `~/.yeaboi/logs/<mode>/<mode>.log` while a mode page runs (standup, retro, performance, reporting, analysis). Idempotent + detaches on exception. The analysis branch uses explicit `attach_mode_handler`/`detach` (too large for a `with` block)
- `attach_session_log(session_id)` / `detach_session_log()` — per-planning-session log (`~/.yeaboi/logs/planning/{session-id}.log`); called via `persistence.attach_session_logger`
- `apply_level(level)` — retunes the `yeaboi` logger + every attached handler live (used by the Settings page)

Log files:
- **Main/TUI**: `~/.yeaboi/logs/tui/yeaboi.log` (always on)
- **Per mode**: `~/.yeaboi/logs/{standup,retro,performance,reporting,analysis}/<mode>.log` — active while that page runs; the scheduled headless standup (`--standup-run`) also writes `standup/standup.log`
- **Planning sessions**: `~/.yeaboi/logs/planning/{session-id}.log` (deleted with the project, including `.log.N` rotation backups)
- **Analysis text reports**: `team-analysis-{project}-{timestamp}.log` in `logs/analysis/` — a hand-written product artifact from `team_profile_exporter`, not a logging handler

Rules:
- Log level: `LOG_LEVEL` env var (`DEBUG`/`INFO`/`WARNING`/`ERROR`, default `WARNING`) — settable via `.env` or the Settings page **Log Level** cycle button (`config.set_log_level()` + `apply_level()`)
- **Never log in per-frame code**: `_build_*_screen` builders and render paths run every frame (~60 fps); `logger.info` belongs in key-handling branches of runner loops and one-shot functions only
- INFO = user actions / page open-close / generate / export / config changes; DEBUG = action-time detail; WARNING/ERROR = every failure path. Never log secrets, tokens, join codes, or user content — log ids, counts, names, paths
- All paths defined in `src/yeaboi/paths.py` — never hardcode `Path.home() / ".yeaboi"`
- LangSmith 429 rate-limit errors are auto-suppressed via a custom logging filter in `__init__.py`
- Token usage is tracked via `track_usage()` in `agent/llm.py` and persisted to `token_usage` table in SQLite

## Environment Setup

- `ANTHROPIC_API_KEY` — required when using Anthropic (default provider)
- `OPENAI_API_KEY` — required when `LLM_PROVIDER=openai`
- `GOOGLE_API_KEY` — required when `LLM_PROVIDER=google`
- `AWS_REGION` — required when `LLM_PROVIDER=bedrock` (auto-detected from `~/.aws/config` on Lightsail)
- `AWS_PROFILE` — optional, auto-detected from `~/.aws/config` (looks for profiles with `credential_source` or `role_arn`)
- `LLM_PROVIDER` — `anthropic` (default), `openai`, `google`, `bedrock`
- `LLM_MODEL` — optional model override for the selected provider
- `GITHUB_TOKEN`, `AZURE_DEVOPS_TOKEN` — optional, for repo context tools
- `AZURE_DEVOPS_ORG_URL`, `AZURE_DEVOPS_PROJECT`, `AZURE_DEVOPS_TEAM` — optional, for Azure DevOps board sync
- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` — optional, for Jira integration
- `CONFLUENCE_SPACE_KEY` — optional, the space to scope searches to; the Export buttons publish Confluence reports here too
- `CONFLUENCE_BASE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` — optional standalone Atlassian login for Confluence. Confluence reuses the Jira creds by default; these let it be configured **without** Jira (they win over `JIRA_*` when set — see `config.get_confluence_base_url`). The Docs setup step collects them inline when Jira wasn't configured.
- `NOTION_TOKEN` — optional, Notion integration token (independent doc tool; its own auth, not shared with Jira/Confluence). Enables the 5 `notion_*` tools + analysis/standup context.
- `NOTION_ROOT_PAGE_ID` — optional, default parent for created Notion pages; also gates the Notion source in the Daily Standup activity feed (the Confluence-space-key analog)
- `YEABOI_HOME` — optional, relocates the whole data tree (exports, logs, sessions DB, scrum-docs…; default `~/.yeaboi`). Resolved once at import time in `paths.py` (`_resolve_root()`); `.env` itself always stays at `~/.yeaboi/.env` (the bootstrap file that holds this var). Editable in the TUI via Settings → Data Dir, which offers to move the existing tree (`paths.move_data_tree`) and notes a restart is needed to fully apply.
- `NOTION_EXPORT_PARENT_PAGE_ID` — optional, a dedicated Notion page the Export buttons publish under; **blank groups exports under an auto-created "yeaboi" page (🤙 icon) inside `NOTION_ROOT_PAGE_ID`**. With neither set, Notion export shows a warning pointing at Setup (the Notion API can't create top-level pages).
- `CONFLUENCE_EXPORT_PARENT_PAGE_ID` — optional page Confluence exports nest under; blank groups them under an auto-created "🤙 yeaboi" page at the root of `CONFLUENCE_SPACE_KEY` (no space key → warning pointing at Setup).
- `STANDUP_USER_NAME` — optional, your display name for your own standup update (default: "Me")
- `STANDUP_GITHUB_REPO` — optional, GitHub repo (owner/repo) scanned for Daily Standup code activity
- `SLACK_WEBHOOK_URL` — optional, Slack incoming-webhook URL for Daily Standup delivery
- `STANDUP_SMTP_HOST` / `STANDUP_SMTP_PORT` / `STANDUP_SMTP_USER` / `STANDUP_SMTP_PASSWORD` / `STANDUP_SMTP_SENDER` / `STANDUP_EMAIL_RECIPIENTS` — optional, SMTP email delivery for Daily Standup
- `RETRO_PORT` — optional, base port for the Retro LAN collaboration server (default 5173; walks upward if busy)
- `CLOUDFLARED_PATH` — optional, path to an existing `cloudflared` binary for Retro remote tunnels (else the app auto-downloads one to `~/.yeaboi/bin/`)
- `PERFORMANCE_FRAMEWORK_PATH` — optional, path to a custom competency framework / review template for Performance mode's 6-month review (else the bundled `performance/references/competency_framework.md` default is used). 1:1 summary emails reuse the standup `STANDUP_SMTP_*` / `STANDUP_EMAIL_RECIPIENTS` settings.
- `SESSION_PRUNE_DAYS` — auto-prune sessions older than N days (default: 30, 0 = disabled)
- `LOG_LEVEL` — file logger level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` — optional, enables LangSmith tracing
- Copy `.env.example` to `.env` and fill in keys (`make env`)
- Never commit `.env` or API keys

## Version Management

Version is **single-sourced in `pyproject.toml`** (`version = "…"`). `src/yeaboi/__init__.py` reads it at runtime from the installed package metadata (`importlib.metadata.version("yeaboi")`, with a `0.0.0+dev` fallback for uninstalled source trees). `__version__` is imported by `cli.py` for the `--version` flag. Package entry points: `yeaboi = "yeaboi.cli:main"` (canonical) and a one-release back-compat alias `scrum-agent = "yeaboi.cli:main"`. The PyPI distribution was renamed `scrum-agent` → `yeaboi`; a thin `scrum-agent` redirect package (`packaging/scrum-agent-shim/`) depends on `yeaboi` so existing installs migrate.

**Releasing is automatic on a version bump.** To ship a release: bump `version` in `pyproject.toml` (semver) and merge to `main`. On that push, `publish.yml` detects there's no `v<version>` tag yet and runs test → build → PyPI publish (OIDC) → creates the `v<version>` tag + GitHub Release. Merges that don't change the version are a no-op. Never tag manually — the workflow owns tagging.

**The bump itself is automated too (`auto-version.yml`).** On each PR, cheap deterministic guards run first (skip if the version was already changed in the PR, or if no `src/yeaboi/**` files changed and no `semver:*` label is present); otherwise Claude classifies the diff into a semver level and commits `chore: bump version to X.Y.Z [auto]` **to the PR branch** — so merging fires `publish.yml` with no manual step. Rules:
- **Bump on the PR branch, not `main`** — a workflow pushing to `main` with the default `GITHUB_TOKEN` would not re-trigger `publish.yml` (recursion suppression); the human merge does. This means no PAT is needed.
- **Override with a label**: `semver:major` / `semver:minor` / `semver:patch` forces the level; `release:skip` (or `semver:none`) suppresses the bump.
- **Manual bumps still work** — if you edit `version` yourself, the guard sees it already differs from `main` and leaves it alone.
- **Mechanics** live in `scripts/bump_version.py` (pure `bump()` + `make bump-patch|bump-minor|bump-major`); the LLM only chooses the level.
- **Known limitation**: two PRs branched off the same version can pick the same next version — whichever merges second finds the tag already exists and won't publish separately. Acceptable for this repo; the fix (post-merge serialized bump on `main`) would need a PAT to re-trigger `publish.yml`.

Distribution is PyPI-only (via `uv tool install` / `pipx install`); Homebrew is not supported because a required dependency (`sqlite-vec`) ships no sdist, so the `omardin14/homebrew-tap` formula is permanently disabled.

## CI/CD

Workflows in `.github/workflows/`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Every push | Lint + test |
| `auto-version.yml` | PR | Claude classifies the diff and commits a `chore: bump version…` to the PR branch (skips docs/chore-only PRs; `semver:*` / `release:skip` labels override) |
| `publish.yml` | Push to `main` | if `pyproject.toml` version has no tag yet: test → build → PyPI publish (OIDC) → tag + GitHub Release (else no-op) |
| `smoke.yml` | Weekly cron | Live API smoke tests |
| `security-scan.yml` | Weekly cron + manual | SAST + dependency CVE audit (PRs get the same scan via ci.yml's `make security` job) |
| `claude.yml` | `@claude` mention in an issue/PR comment | On-demand Claude Code assistance (the auto-run per-PR review workflow was removed — it was too slow) |

There is no Homebrew tap auto-update: the `omardin14/homebrew-tap` formula is disabled (see Version Management) and `publish.yml` no longer dispatches to it.

## OpenClaw Skill

The `skills/scrum-planner/` directory contains an OpenClaw skill that replicates the smart intake TUI experience conversationally. OpenClaw acts as the front-end (asks questions, handles follow-ups), then invokes `yeaboi --non-interactive` as the back-end.

**How it works:**
1. OpenClaw asks ~7 essential questions (matching `SMART_ESSENTIALS` from `prompts/intake.py`)
2. Answers map to: Q1/Q6/Q8 → CLI args, everything else → temp `SCRUM.md` in CWD
3. Invokes: `yeaboi --non-interactive --description "Q1" --team-size Q6 --sprint-length Q8 --output json`
4. `_load_user_context()` in `nodes.py` reads the SCRUM.md from CWD, `_keyword_extract_fallback()` does keyword scanning
5. JSON output is parsed and presented to the user

**Key files:**
- `skills/scrum-planner/SKILL.md` — agent instructions (persona, conversation flow, SCRUM.md generation, CLI invocation, output formatting)
- `skills/scrum-planner/README.md` — installation and usage docs
- `skills/scrum-planner/scripts/` — helper scripts for the skill
- `skills/scrum-planner/references/` — reference material

**Installing the skill:**
```bash
yeaboi --install-skill          # installs to ~/.openclaw/skills/
yeaboi --install-skill /path    # custom directory
```

## Daily Standup Mode

The `src/yeaboi/standup/` package implements a daily scrum that detects team activity, scores sprint progress, and delivers a summary — runnable from the TUI or headlessly on an OS schedule.

**Design choice — standalone pipeline, not a LangGraph node.** `engine.run_standup()` calls `get_llm()`/`track_usage()` directly following the node **parse → fallback → format** convention, but is *not* a compiled graph — the scheduled headless run must be fast and checkpoint-free. Activity gathering + confidence are deterministic function calls; the LLM is used only to synthesize prose (one call).

**Pipeline** (`engine.run_standup(session_id)`): load session state + `StandupStore.load_config` → `collector.collect_recent_activity` (fan-out, graceful per-source skip) → `sprint_context.gather` + `confidence.compute` (deterministic sprint day + burn-down) → self-reported updates verbatim / others summarized by one LLM call → `StandupReport` → `delivery.deliver` → `StandupStore.record_run`.

**Recent-activity helpers** are plain functions (not `@tool`) on each tool module: `jira_recent_activity`, `azdevops_recent_activity`, `github_recent_commits`/`github_recent_prs`, `confluence_recent_pages`, `tools/local_git.local_git_recent_commits`, plus `*_active_sprint_progress` for burn-down. All return normalized `list[dict]` and degrade to `[]` on error. The collector lazy-imports them (optional SDKs).

**Scheduling** (`scheduler.py`) is OS-native so standups fire when the app is closed. The user configures the **standup time** (when the meeting happens) + `lead_minutes` (default 10); the job fires `standup_time − lead` (`run_time()` helper). On macOS it opens a **Terminal** at run time (a launcher script under `~/Library/Application Support/yeaboi/` + `osascript`) so the run can prompt; on Linux it's a crontab entry that runs headless. Both invoke `yeaboi --standup-run --standup-interactive --standup-session <id>`; `interactive.py` prompts only when a TTY is attached, else falls back to headless. Windows is unsupported (graceful message).

**Warnings, not empty content** (`errors.py` + engine): activity helpers raise `StandupSourceError` on 401/403 → collector records `ActivityBundle.errors`. The engine also checks `config.is_llm_configured()` and catches LLM auth/billing errors (no longer re-raised) — all fold into `StandupReport.warnings`, rendered as a **⚠ Notices** section in the dashboard and delivery output. `Generate` also prompts for the user's own update first (`STANDUP_USER_NAME`, default "Me").

**Delivery** (`delivery.py`) is stdlib-only: Terminal (Rich), Desktop (`osascript`/`notify-send`), Slack (`urllib` webhook), Email (`smtplib`). `deliver()` fans out and returns per-channel status; one channel failing → `status="partial"`, never raises.

**Persistence**: `store.py` defines `_STANDUP_SCHEMA` (schema v6 in `sessions.py`) with `standup_config` / `standup_history` / `standup_updates`. `StandupReport`/`MemberUpdate` are frozen dataclasses in `agent/state.py` (all fields defaulted for backward-compat).

**TUI**: the magenta **Standup** card → `_build_standup_screen` + `_run_standup_page` in `ui/mode_select/`, with **Generate / My Update / Configure / Export / Back** actions. Logs go to `~/.yeaboi/logs/standup/`; readable output (Markdown + HTML) is auto-saved to `~/.yeaboi/exports/standup/<project>/` every run and via the Export button (`export.py`, `paths.get_standup_export_dir`).

## Retro Mode

The `src/yeaboi/retro/` package implements a **collaborative** sprint retrospective: the host opens the Retro page and teammates add sticky cards to four grids — *What went well*, *What didn't go well*, *Action items*, *Demos* — from their own browsers on the LAN.

**Design choice — LAN browser board, stdlib-only.** A retro needs the whole team, but the app is a local terminal tool. So the host's TUI starts a small **`http.server.ThreadingHTTPServer`** (NOT FastAPI/Flask — matches the stdlib-only ethos of `standup/delivery.py`) bound to `0.0.0.0`, and shows a **share code + URL**. Teammates open the URL in any browser (no install) and POST cards; the page (`page.py`) polls every 2 s. There is **no new dependency**.

**Live board + thread safety** (`board.py`): `RetroBoard` is the single source of truth during a session — a `threading.Lock`-guarded card list with a `_revision` counter. The background HTTP threads call `add_card`; the TUI render thread calls `snapshot()`/`cards_by_grid()` each frame. Readers copy inside the lock and render outside it; the lock never wraps a Rich render or JSON dump. **No extra TUI-side thread is needed** — the existing frame-timed `read_key` loop re-renders from `snapshot()` every frame, so cards appear within one frame. `RetroCard`/`RetroReport` are frozen dataclasses in `agent/state.py` (all fields defaulted).

**Security** (`server.py`): access is gated by a per-session `secrets.token_urlsafe(16)` token checked with `secrets.compare_digest`; `GET /` serves the harmless page but every `/api/*` call requires the token. POST body capped 4 KB, card text ≤500 / author ≤60. It's a **LAN-trust model, no TLS — do not port-forward.** Card text is escaped on browser render (`textContent`), in exported HTML (`html.escape`), and framed as untrusted data in the LLM prompt. Concurrency: `daemon_threads=True`; `shutdown()` is called from the TUI thread (never the server thread — deadlock), then `server_close()`; every response sets `Content-Length` (HTTP/1.1 keep-alive).

**AI action items** (`engine.py`): `generate_action_items(board)` makes one `get_llm()` call (prompt in `prompts/retro.py`, ARC framework) from the "didn't go well" cards (+ selectively "went well"), following the standup **parse → fallback** convention — an auth/billing error becomes a status message + deterministic fallback, never a crash. Added cards get `origin="ai"` and are badged in both the TUI and browser.

**Persistence & export**: `store.py` defines `_RETRO_SCHEMA` (schema **v7** in `sessions.py`) with one `retro_history` table; the board is flushed via `RetroStore.record_run` in a `finally` on page exit. `export.py` writes Markdown + HTML to `~/.yeaboi/exports/retro/<project>/` (`paths.get_retro_export_dir`), reusing `html_exporter._CSS`.

**Live web interface** (`page.py`, one self-contained offline page): teammates get emoji **reactions** on cards (fixed `REACTION_EMOJIS` set, click to toggle), **drag** to reorder/move cards between grids, **edit/delete** their *own* cards (author-only), a shared **countdown timer** (presets + custom, synced via the server clock, **confetti + Web-Audio alarm** on finish), a join modal with an **avatar picker** + 🎲 **random-name** generator (**renamable later** via the `#me` pill), a **theme switcher** (5 `[data-theme]` palettes), and **Web-Audio-generated music** (ambient/lofi/focus/**hip-hop**/**jazz**, no files, offline) with a live `AnalyserNode` **visualizer**. The **header** is a compact toolbar: brand + card count, a distinct "you" `me-chip`, an **others-only** overlapping-avatar presence stack (the current user is filtered out so they're never shown twice), a **👥 room count** that opens a left-anchored **roster** popover listing everyone present (you tagged "you", live "typing…" tags), and small icon buttons (`♪` Music / `⏱` Timer / `◑` Theme / Invite) that each open a **popover** (`.pop`, one open at a time, closed on click-outside/Esc) holding that control's UI — Theme is a row of colour **swatches**, the running timer's `MM:SS` shows inline on its button. Per-grid **typing indicators** sit under each column. All of it is driven by a **unified `/api/state`** polled ~1.2 s — the page POSTs `/api/presence` (heartbeat + fetch in one round-trip) and renders the returned `{cards, reactions, presence, typing, timer}`; each card carries a `mine` flag (owner == viewer `pid`) that drives the ✎/✕ controls without ever putting raw pids on the wire. Reactions/presence/typing/timer/ownership are lock-guarded board state (`board.py`); `REACTION_EMOJIS`/`AVATARS` are server-validated (LAN peers untrusted). Card mutations go through `/api/card/{edit,delete,move}` (edit/delete owner-checked server-side; move open to all). Reactions fold into `RetroCard.reactions` at report time (shown in MD/HTML exports; fed to the AI as a priority hint). The big CSS/JS lives in plain `_CSS`/`_JS` module strings filled by placeholder `str.replace`; `page.py` is E501-exempt in `pyproject.toml` as an embedded asset.

**Joining & token security** (`server.py`): the served `/` page is **token-free** — `GET /` is unauthenticated, so the token is *never* baked into the HTML (it would leak to any LAN peer). The client reads the token from its own URL `?token=`, or a teammate opens the bare host address and types the short **join code** into the code-entry gate → `POST /api/join` (unauthenticated; `compare_digest(code, join_code)` → returns the token). `RetroServer.join_code` (an 8-char unambiguous code, shown in the TUI as `display_code`) is a LAN-trust convenience credential; the 128-bit `token` still guards direct URLs/QR. `GET /api/qr` (token-gated) renders a scannable **QR** of `scheme://<Host header>/?token=…` via `segno` (pure-python dep) — the Host header makes it correct for LAN *and* tunnel automatically, and being token-gated it can't leak the token to unauthenticated visitors.

**Remote joining — Cloudflare tunnel** (`tunnel.py`): the LAN server only reaches same-network teammates. The **Share Remotely** button starts a **Cloudflare quick tunnel** (`cloudflared tunnel --url http://localhost:<port>`) exposing a public `https://…trycloudflare.com` URL that forwards to the token-gated server. It's genuinely **zero-setup**: no Cloudflare account/token (unlike ngrok, which forces a per-user authtoken), so the app owns the whole flow — `ensure_cloudflared()` downloads the platform binary on first use to `~/.yeaboi/bin/` (cached; honours a `cloudflared` already on PATH or `CLOUDFLARED_PATH`). Setup runs on a **worker thread** (download + handshake are slow) while the frame-timed loop shows progress; the button toggles **Stop Sharing**. The tunnel is torn down in the page's `finally`. Everything is best-effort — a failed download/tunnel never raises, the retro stays LAN-only. The public URL is internet-reachable while up (token-gated, HTTPS); the browser page uses relative fetch URLs so it works identically over LAN or tunnel.

**TUI**: the teal **Retro** card → `_build_retro_screen` + `_run_retro_page` in `ui/mode_select/`, with **Generate Action Items / Share Remotely / Export / Close** actions. Targets the most recent session; logs go to `~/.yeaboi/logs/retro/`. Configure the server port with `RETRO_PORT` (default 5173, walks upward if busy).

## Performance Mode

The `src/yeaboi/performance/` package helps a team lead manage each engineer with three connected, LLM-backed workflows. It follows the **standup/retro blueprint** exactly: a self-contained package (`engine` + `store` + `render`/`export`), frozen-dataclass artifacts in `agent/state.py`, a SQLite schema bumped in `sessions.py`, a TUI page via the shared component system, and a `gather_performance_context()` reader that feeds Planning & Analysis.

**Design choice — standalone pipelines, not LangGraph nodes.** Each workflow (`engine.run_one_on_one_prep`, `complete_one_on_one`, `run_six_month_review`) is one deterministic gather step + a single `get_llm()`/`track_usage()` call following the node **parse → fallback → format** convention. An LLM auth/billing error is *never* re-raised — it becomes a `warnings` entry + a deterministic fallback artifact, so the page always renders.

**Roster from Jira/AzDO** (`roster.py`): `fetch_roster()` derives the engineer list from the *assignees who actually did work* (reuses `jira_recent_activity`/`azdevops_recent_activity`), not the plan's team-size number. Graceful `[]` when no tracker is configured. `activity.py:gather_engineer_activity()` filters recent activity to one engineer and splits it into current/previous sprint by the live sprint start date (reuses standup `sprint_context`).

**Three workflows:**
- **1:1 Prep** — from the engineer's current+prior-sprint tickets and the open action items of their last 1:1, produces `OneOnOnePrep` (talking points, feedback, goals, gaps, improvements).
- **1:1 Completion** — the lead provides a transcript (file import *or* inline paste); produces `OneOnOneRecord` (email summary + tracked `action_items`), emails it via SMTP (reuses standup `config.get_smtp_*`), and persists the actions so the **next** prep carries them (the Prep↔Completion loop closes via `PerformanceStore.get_open_action_items`).
- **6-Month Review** — synthesises past 1:1s + Jira/AzDO delivery history + ceremony history + lead notes + a competency framework into `SixMonthReview`. The framework is the bundled `performance/references/competency_framework.md` by default, overridable with a lead's own template via `PERFORMANCE_FRAMEWORK_PATH`.

**Feeds Planning & Analysis** (`context.py`): `gather_performance_context()` mirrors `agent/ceremony_history.py` — team-wide, graceful, distils per-engineer open 1:1 actions + review growth areas into a markdown block injected into the analyzer (`performance_context` param) and sprint planner (via `ScrumState._performance_context`). Only already-summarised signals cross the boundary — never raw transcripts.

**Persistence**: `store.py` defines `_PERFORMANCE_SCHEMA` (schema **v8** in `sessions.py`) with `performance_one_on_ones` / `performance_reviews` / `performance_notes`. `EngineerRef`/`EngineerActivity`/`OneOnOnePrep`/`OneOnOneRecord`/`SixMonthReview` are frozen dataclasses in `agent/state.py` (all fields defaulted for backward-compat). Readable output (Markdown + HTML) auto-saves to `~/.yeaboi/exports/performance/<engineer>/` every run and via the Export button.

**TUI**: the coral **Performance** card → `_build_performance_screen` + `_run_performance_page` in `ui/mode_select/`. Two views: a **roster** (↑/↓ select an engineer) with **1:1 Prep / 1:1 Complete / 6mo Review / Notes / Export / Back** actions, and a **detail** view showing the produced artifact (scroll + Export/Back). Logs go to `~/.yeaboi/logs/performance/`.

## Reporting Mode

The `src/yeaboi/reporting/` package produces a **business-friendly summary of delivered work** to relay back to stakeholders — for either **the last sprint** or **the last ~month (~2 sprints)**. It follows the **standup/retro/performance blueprint** exactly: a self-contained package (`engine` + `store` + `render`/`export` + `presentation`), a frozen-dataclass artifact in `agent/state.py`, a SQLite schema bumped in `sessions.py`, and a TUI page via the shared component system.

**Design choice — standalone pipeline, not a LangGraph node.** `engine.run_delivery_report(period)` is one deterministic gather step + a single `get_llm()`/`track_usage()` "design" call following the node **parse → fallback → format** convention. An LLM auth/billing error is *never* re-raised — it folds into `warnings` + a deterministic fallback report (counts + item list + generic emojis), so the page always renders.

**Data source — trackers.** `activity.gather_delivered_work(period)` pulls team-wide recent activity via the same helpers the standup uses (`jira_recent_activity` / `azdevops_recent_activity`) + `standup/sprint_context.gather` for sprint dates, then keeps only tickets whose status means *done* (`_COMPLETED_STATUSES`: done/closed/resolved/released/completed/…). Look-back = one sprint length for "last sprint", `max(28, 2×sprint_weeks×7)` days for "last month". Graceful `[]` + a warning when no tracker is configured.

**Whole-quarter period.** A third period reports on a **calendar quarter** (Q1 starts January). `sprints.quarter_bounds(today)` detects the current quarter (`Q3 2026`); `sprints.list_sprints()` returns real sprints with date ranges — **live tracker first** (new `jira_list_sprints` / `azdevops_list_sprints` helpers reusing the board/iteration discovery) then **plan-derived** dates (`sprint_start_date` + `sprint_length_weeks`×idx) as a fallback. The TUI shows a **sprint multi-select** (`sprint_select` view): ~12 sprints, the quarter's overlapping ones pre-checked (`mark_in_quarter`), Space toggles, Enter generates. The checked sprints' date span becomes the window: `run_delivery_report(PERIOD_QUARTER, window_start=min start, window_end=min(max end, today), sprint_names=…, period_label_override="Q3 2026")` (`(custom)` suffix when the selection differs from the detected set); `gather_delivered_work(days_override=…)` reports over that span. No tracker/plan sprints → the multi-select is skipped and it reports over the calendar-quarter dates. A truncation notice is added since the activity helpers cap at ~100 rows/source.

**Hybrid presentation** (the user's chosen approach): the LLM design call supplies the *content* — the executive narrative, the outcome **themes**, the **highlights**, and one **emoji per section slot** (parsed by `engine._parse_themes` / `_parse_emoji`, with a deterministic `_DEFAULT_EMOJI` fallback). `presentation.build_presentation_html()` only *renders* it into a **self-contained, offline HTML slide deck** (inline `_CSS`/`_JS` module strings filled by `str.replace`, same embedded-asset pattern as `retro/page.py`, E501-exempt in pyproject): Title → Executive summary → Metrics → per-Theme → Highlights → Thank-you, with keyboard nav (←/→/Space), a progress bar, and 4 `[data-theme]` palettes cycled with **T**. Slide data is injected as a JSON blob and rendered via `textContent`; `_json_for_script()` escapes `<`/`>`/`&` to `\uXXXX` so an untrusted ticket title can't break out of the `<script>` (defense in depth).

**Persistence & export**: `store.py` defines `_REPORTING_SCHEMA` (schema **v9** in `sessions.py`) with one `reporting_history` table. `DeliveryReport`/`DeliveredItem` are frozen dataclasses in `agent/state.py` (all fields defaulted; `themes`/`metrics`/`emoji_theme` are tuple-of-pairs so the whole artifact stays serializable). `export.export_report()` auto-saves **Markdown + HTML + slide deck** to `~/.yeaboi/exports/reporting/<project>/` every run and via the Export button; the HTML report reuses `html_exporter._CSS`, all tracker text `html.escape`-d.

**TUI**: the indigo **Reporting** card → `_build_reporting_screen` + `_run_reporting_page` in `ui/mode_select/`. Three views: a **picker** (↑/↓ choose Last sprint / Last month / Whole quarter) with **Generate Report / Theme / Back**; a **sprint_select** checkbox list (↑/↓ move, Space toggle, Enter generate) shown when generating a quarter; and a **detail** view of the generated report (scroll + **Export / Theme / Back**; Theme cycles the slide-deck palette). Targets the most recent session for sprint length / project name. Logs go to `~/.yeaboi/logs/reporting/`.

## Deployment (AWS Lightsail)

yeaboi is deployed on AWS Lightsail via the OpenClaw blueprint:
- OpenClaw comes pre-installed on the Lightsail instance
- Uses Amazon Bedrock (Claude Sonnet 4.6) via IAM instance role — no API key needed
- Bedrock IAM setup script: `curl -s https://d25b4yjpexuuj4.cloudfront.net/scripts/lightsail/setup-lightsail-openclaw-bedrock-role.sh | bash -s -- <instance-name> <region>`
- The setup wizard auto-detects the AWS region from `~/.aws/config` and the Bedrock model from OpenClaw's `models.json`
- See README section "Deploy on AWS Lightsail (OpenClaw)" for full guide

## Git Conventions

- **Commit messages**: lowercase imperative (e.g. "add streaming output", "fix import sorting")
- **Branch naming**: `feature/<description>` for feature work
- **PRs**: feature branches merge to `main` via pull request
- Include `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>` on AI-assisted commits
