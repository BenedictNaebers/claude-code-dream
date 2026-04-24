#!/usr/bin/env bash
# ccdream status-line snippet. Emits a compact one-liner or nothing.
# Designed for appending to an existing statusLine command.
#
# Outputs (without trailing newline):
#   ⏳ dream: <slug>    — worker currently running; <slug> is the in-flight project
#   ⏳ dream            — worker running but no project progress line yet
#   ⚠ dream failed      — last run set the failure flag
#   (silent)            — idle / last run succeeded

DREAM_DIR="${HOME}/dream"

if [ -d "$DREAM_DIR/.run.lock" ]; then
  log="$DREAM_DIR/logs/daily/$(date +%F).log"
  slug=""
  if [ -f "$log" ]; then
    slug=$(grep '^--- project:' "$log" 2>/dev/null | tail -1 | sed 's|^--- project: ||; s|.*/||')
  fi
  if [ -n "$slug" ]; then
    printf '⏳ dream: %s' "$slug"
  else
    printf '⏳ dream'
  fi
  exit 0
fi

if [ -f "$DREAM_DIR/.last_run_failed" ]; then
  printf '⚠ dream failed'
fi
