#!/usr/bin/env bash
# Terse, deterministic one-screen summary of the ccdream plugin state.
# Used by /ccdream:dream-status. No model interpretation; just print facts.

set -u

DREAM_DIR="${HOME}/dream"
STAMP="${DREAM_DIR}/.last_run_date"
FAIL_FLAG="${DREAM_DIR}/.last_run_failed"
LOCK="${DREAM_DIR}/.run.lock"
LOG_DIR="${DREAM_DIR}/logs/daily"
PENDING_DIR="${DREAM_DIR}/pending"

# Portable stat: BSD (macOS) uses -f, GNU (Linux) uses -c.
if stat -f '%m' / >/dev/null 2>&1; then
  stat_mtime() { stat -f '%m' "$1"; }
else
  stat_mtime() { stat -c '%Y' "$1"; }
fi

# 1. In-progress? (lock held)
if [ -d "$LOCK" ]; then
  today_log="$LOG_DIR/$(date +%F).log"
  current=""
  if [ -f "$today_log" ]; then
    current=$(grep '^--- project:' "$today_log" 2>/dev/null | tail -1 | sed 's|^--- project: ||; s|.*/||')
  fi
  if [ -n "$current" ]; then
    echo "Worker in progress — current project: $current"
  else
    echo "Worker in progress — tailing $today_log would show live output"
  fi
else
  if [ -f "$STAMP" ]; then
    echo "Last run: $(cat "$STAMP")"
  else
    echo "Last run: never"
  fi
  if [ -f "$FAIL_FLAG" ]; then
    latest_log=$(ls -t "$LOG_DIR" 2>/dev/null | head -1)
    echo "Last run: FAILED — see $LOG_DIR/${latest_log:-?}"
  fi
fi

# 2. Pending items per slug.
found_any=0
if [ -d "$PENDING_DIR" ]; then
  for slug_dir in "$PENDING_DIR"/*/; do
    [ -d "$slug_dir" ] || continue
    slug=$(basename "$slug_dir")
    count=0
    oldest_ts=""
    for f in "$slug_dir"*.md; do
      [ -f "$f" ] || continue
      count=$((count + 1))
      ts=$(stat_mtime "$f" 2>/dev/null || echo "")
      [ -z "$ts" ] && continue
      if [ -z "$oldest_ts" ] || [ "$ts" -lt "$oldest_ts" ]; then
        oldest_ts="$ts"
      fi
    done
    if [ "$count" -gt 0 ]; then
      if [ -n "$oldest_ts" ]; then
        age_days=$(( ( $(date +%s) - oldest_ts ) / 86400 ))
        echo "$slug: $count pending, oldest ${age_days}d"
      else
        echo "$slug: $count pending"
      fi
      found_any=1
    fi
  done
fi
if [ "$found_any" -eq 0 ]; then
  echo "No pending review items."
fi

echo "Use /dream-review in a project directory to walk through its pending items."
