#!/usr/bin/env bash
# w <name> [open|rm] — git worktree lifecycle for yeaboi.ai.
#
#   ./scripts/w.sh issue-12        create ../ai-manager-issue-12 on branch issue-12
#   ./scripts/w.sh issue-12 open   create (if needed) + launch claude inside it
#   ./scripts/w.sh issue-12 rm     remove the worktree dir + local branch
#
# Each worktree gets a deterministic dev-server port (see the Makefile's
# YB_DEV_PORT), so you can run `make dev` in several worktrees at once without
# port collisions. No database — worktrees are just isolated checkouts.
set -euo pipefail

NAME="${1:?usage: w <name> [open|rm]}"
ACTION="${2:-create}"
ROOT="$(git rev-parse --show-toplevel)"
PARENT="$(dirname "$ROOT")"
TARGET="$PARENT/$(basename "$ROOT")-$NAME"

if [ "$ACTION" = "rm" ]; then
  git -C "$ROOT" worktree remove --force "$TARGET" 2>/dev/null || true
  rm -rf "$TARGET"
  git -C "$ROOT" worktree prune
  git -C "$ROOT" branch -D "$NAME" 2>/dev/null || true
  echo "[w] removed $TARGET (branch $NAME)"
  exit 0
fi

if [ ! -d "$TARGET" ]; then
  git -C "$ROOT" worktree add "$TARGET" -b "$NAME"
  echo "[w] created $TARGET on branch $NAME"
else
  echo "[w] reusing $TARGET"
fi

# Informational: the worktree's deterministic dev port.
PORT="$(cd "$TARGET" && make -s port 2>/dev/null || true)"
[ -n "$PORT" ] && echo "[w] dev port: $PORT  (run 'make dev' inside the worktree)"

echo "[w] worktree: $TARGET"
if [ "$ACTION" = "open" ]; then
  (cd "$TARGET" && claude --dangerously-skip-permissions)
fi
