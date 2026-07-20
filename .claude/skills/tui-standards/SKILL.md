---
name: tui-standards
description: TUI component standards — shared primitives in ui/shared/_components.py, the mandatory Panel page structure, themes, buttons, scrollbars, viewport math. Use when creating or modifying any TUI screen, any _build_*_screen function, or code under src/yeaboi/ui/.
---

# TUI Component Standards

All TUI screens MUST use the shared component system in `src/yeaboi/ui/shared/_components.py`. Do NOT duplicate rendering logic.

## Shared Primitives (use these, don't rewrite)

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

## Page Structure (every `_build_*_screen` function MUST follow)

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

## Rules

1. **DRY** — Never inline button rendering, scrollbar math, or viewport calculations. Always use shared functions.
2. **Themes** — Never hardcode colour values (`"rgb(100,180,100)"`). Use `theme.accent`, `theme.muted`, etc. from the appropriate Theme constant.
3. **New pages** — Adding a new mode/page requires: a Theme constant, a `*_title()` function, a colour entry in `COLOR_RGB`, and an entry in `_MODE_CARDS` (if it's a main menu item).
4. **Consistency** — All pages use the same Panel structure (title → subtitle → viewport → buttons). No exceptions.
5. **Scrollbar** — Content that can overflow MUST use `build_scrollbar()`. Use `always_show=True` for pages where the track should always be visible.
6. **Buttons** — Register new button labels in `_BTN_COLORS` dict in `_components.py` with accent/grey colour tuples.
7. **No `_PAD` aliases** — Import `PAD` directly from `yeaboi.ui.shared._components`. Legacy `_PAD = PAD` aliases exist but should not be added to new files.
8. **Never log in per-frame code** — `_build_*_screen` builders and render paths run every frame (~60 fps); `logger.info` belongs in key-handling branches of runner loops and one-shot functions only (see the `logging` skill).
