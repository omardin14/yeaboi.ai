#!/usr/bin/env bash
# Claude Code PostToolUse hook (Edit|Write): auto-format the touched Python file
# with ruff so every edit lands pre-formatted and lint round-trips disappear.
#
# Receives the hook payload as JSON on stdin; extracts tool_input.file_path.
# Best-effort by design: non-.py files, missing files, and ruff errors all
# exit 0 — formatting must never block the session.

set -uo pipefail

file_path="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))' 2>/dev/null)"

[ -n "${file_path}" ] || exit 0
case "${file_path}" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "${file_path}" ] || exit 0

# Same uv fallback as the Makefile; plain ruff if uv is absent.
if command -v uv >/dev/null 2>&1; then
  RUFF="uv run ruff"
elif [ -x "${HOME}/.local/bin/uv" ]; then
  RUFF="${HOME}/.local/bin/uv run ruff"
else
  RUFF="ruff"
fi

${RUFF} format -q "${file_path}" 2>/dev/null || true
${RUFF} check -q --fix "${file_path}" 2>/dev/null || true
exit 0
