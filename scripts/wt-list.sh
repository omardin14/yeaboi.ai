#!/usr/bin/env bash
# scripts/wt-list.sh — list every git worktree with branch, clean/dirty status,
# and path. Backs `make wt-list`. The main checkout is included, marked (main).

set -euo pipefail

# Colours only when stdout is a terminal — `make wt-list | grep …` stays clean.
if [ -t 1 ]; then
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; DIM=""; BOLD=""; RESET=""
fi

# Self-heal a stray `core.bare=true` left by an interrupted parallel session
# (see scripts/wt.sh) so `make wt-list` never dies with "must be run in a work tree".
git config core.bare false 2>/dev/null || true

MAIN_ROOT="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"

printf "%s%-24s  %-7s  %s%s\n" "$BOLD" "BRANCH" "STATUS" "PATH" "$RESET"
printf "%s%-24s  %-7s  %s%s\n" "$DIM" "------" "------" "----" "$RESET"

# `git worktree list --porcelain` stanzas:
#   worktree <abs-path>
#   HEAD <sha>
#   branch refs/heads/<name>     (or `detached`)
git worktree list --porcelain | awk '
  /^worktree /  { wt=$2 }
  /^branch /    { print wt "\t" $2 }
  /^detached$/  { print wt "\t(detached)" }
' | while IFS=$'\t' read -r wt branch; do
  short_branch="${branch#refs/heads/}"
  [ "$wt" = "$MAIN_ROOT" ] && short_branch="$short_branch (main)"
  if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]; then
    status_cell="${YELLOW}dirty${RESET}  "
  else
    status_cell="${GREEN}clean${RESET}  "
  fi
  printf "%-24s  %s  %s\n" "$short_branch" "$status_cell" "$wt"
done
