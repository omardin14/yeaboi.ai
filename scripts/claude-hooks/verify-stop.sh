#!/usr/bin/env bash
# Claude Code Stop hook: enforce CLAUDE.md's "REQUIRED: Verification" as a
# mechanism instead of a request. When a turn ends with uncommitted Python
# changes, run `make lint` + `make test-fast`; a failure exits 2, which feeds
# the output back to Claude so it fixes the problem before handing work off.
#
# Deliberately same-session and deterministic-only (fast loop). Judgment
# review by an independent session happens at ship time (/ship) and in CI
# (claude-review.yml), not on every stop.

set -uo pipefail

input="$(cat)"

# Claude is already continuing because this hook blocked once this turn.
# Don't block again — prevents infinite loops when the failure needs the
# user (e.g. a broken environment rather than the change itself).
if printf '%s' "${input}" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

# Fast exit for conversational turns: only verify when .py files are dirty.
if ! git status --porcelain 2>/dev/null | grep -qE '\.py$'; then
  exit 0
fi

if ! out="$(make lint 2>&1)"; then
  {
    echo "Stop-hook verification failed: make lint. Fix before finishing (CLAUDE.md REQUIRED: Verification):"
    printf '%s\n' "${out}" | tail -50
  } >&2
  exit 2
fi

if ! out="$(make test-fast 2>&1)"; then
  {
    echo "Stop-hook verification failed: make test-fast. Fix before finishing (CLAUDE.md REQUIRED: Verification):"
    printf '%s\n' "${out}" | tail -50
  } >&2
  exit 2
fi

exit 0
