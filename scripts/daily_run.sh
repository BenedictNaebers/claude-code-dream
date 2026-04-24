#!/usr/bin/env bash
# Orchestrates one day's dream run. Backgrounded by session_start.sh OR run in
# foreground by /dream-run-now.

set -u
export CC_DREAM_SKIP=1

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DREAM_DIR="${HOME}/dream"
STAMP="${DREAM_DIR}/.last_run_date"
FAIL_FLAG="${DREAM_DIR}/.last_run_failed"
LOCK="${DREAM_DIR}/.run.lock"
LOG_DIR="${DREAM_DIR}/logs/daily"
TODAY="$(date +%F)"
LOG_FILE="${LOG_DIR}/${TODAY}.log"

mkdir -p "${DREAM_DIR}" "${LOG_DIR}"

# Always release the lock — even on crash.
cleanup() { rmdir "${LOCK}" 2>/dev/null || true; }
trap cleanup EXIT

# Acquire the lock if we were invoked manually (hook already holds it otherwise).
mkdir "${LOCK}" 2>/dev/null || true

# Portable per-project timeout. GNU coreutils on Linux; homebrew coreutils on
# macOS installs `timeout` (and/or `gtimeout`). Stock macOS has neither — in
# that case we accept uncapped runs rather than hanging the whole pipeline.
run_with_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 600 "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout 600 "$@"
  else
    "$@"
  fi
}

{
  echo "=== ccdream daily run: $(date -Iseconds) ==="
  if [ -n "${CCDREAM_LOOKBACK_DAYS:-}" ]; then
    echo "lookback override: ${CCDREAM_LOOKBACK_DAYS}d"
  fi
  any_failed=0

  # Portable array read: `mapfile` is bash 4+ (not on macOS /bin/bash 3.2).
  PROJECTS=()
  while IFS= read -r project_line; do
    [ -n "${project_line}" ] && PROJECTS+=("${project_line}")
  done < <(python3 "${PLUGIN_ROOT}/scripts/discover_projects.py" | sort)

  if [ "${#PROJECTS[@]}" -eq 0 ]; then
    echo "[ccdream] no eligible projects discovered"
  else
    for project in "${PROJECTS[@]}"; do
      echo "--- project: ${project}"

      # Build dream_run command; only append --lookback-days when the env var
      # is set. Avoid `"${arr[@]:-}"` — bash 3.2 under set -u expands that to a
      # literal empty string, which argparse rejects as an unknown arg.
      DREAM_CMD=(python3 "${PLUGIN_ROOT}/scripts/dream_run.py" --project "${project}")
      if [ -n "${CCDREAM_LOOKBACK_DAYS:-}" ]; then
        DREAM_CMD+=(--lookback-days "${CCDREAM_LOOKBACK_DAYS}")
      fi

      if ! run_with_timeout "${DREAM_CMD[@]}"; then
        echo "[ccdream] dream_run FAILED for ${project}"; any_failed=1; continue
      fi
      if ! run_with_timeout python3 "${PLUGIN_ROOT}/scripts/auto_apply.py" --project "${project}"; then
        echo "[ccdream] auto_apply FAILED for ${project}"; any_failed=1; continue
      fi
    done
  fi

  if [ "${any_failed}" -eq 0 ]; then
    echo "${TODAY}" > "${STAMP}"
    rm -f "${FAIL_FLAG}"
    echo "=== ccdream daily run: success ==="
  else
    touch "${FAIL_FLAG}"
    echo "=== ccdream daily run: finished with failures ==="
  fi
} 2>&1 | tee -a "${LOG_FILE}"
