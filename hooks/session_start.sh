#!/usr/bin/env bash
# SessionStart hook. Must return fast (<100ms). Must not block the session.
#
# Reentrance: Claude Code pipes a JSON payload on stdin, so `[ -t 0 ]` is false
# for EVERY session (interactive or headless) — not a usable signal. We rely on
# two guards:
#   - CC_DREAM_SKIP=1 env var (daily_run.sh exports it before spawning claude -p
#     children, which inherit it);
#   - stamp-file-per-day check (once the day's run succeeded, we skip).

[ "${CC_DREAM_SKIP:-0}" = "1" ] && exit 0

DREAM_DIR="${HOME}/dream"
STAMP="${DREAM_DIR}/.last_run_date"
FAIL_FLAG="${DREAM_DIR}/.last_run_failed"
LOCK="${DREAM_DIR}/.run.lock"
LOG_DIR="${DREAM_DIR}/logs/daily"

mkdir -p "${DREAM_DIR}" "${LOG_DIR}" 2>/dev/null || exit 0

# Surface the last failure (stderr shows in the Claude Code transcript).
if [ -f "${FAIL_FLAG}" ]; then
  LATEST_LOG="$(ls -t "${LOG_DIR}" 2>/dev/null | head -1)"
  echo "[ccdream] last daily run failed; see ${LOG_DIR}/${LATEST_LOG:-?}" >&2
fi

# Already ran today?
if [ -f "${STAMP}" ] && [ "$(cat "${STAMP}" 2>/dev/null)" = "$(date +%F)" ]; then
  exit 0
fi

# Atomic lock. `mkdir` is atomic on POSIX and fails if the dir exists.
mkdir "${LOCK}" 2>/dev/null || exit 0

# Detach. nohup + disown is sufficient on macOS and Linux. `setsid` is NOT
# available on stock macOS; we do not use it. The subshell keeps the
# background job out of the parent's job table.
(
  CC_DREAM_SKIP=1 nohup bash "${CLAUDE_PLUGIN_ROOT}/scripts/daily_run.sh" \
    </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
)

exit 0
