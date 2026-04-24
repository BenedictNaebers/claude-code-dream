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

{
  echo "=== ccdream daily run: $(date -Iseconds) ==="
  any_failed=0

  mapfile -t PROJECTS < <(python3 "${PLUGIN_ROOT}/scripts/discover_projects.py" | sort)

  [ "${#PROJECTS[@]}" -eq 0 ] && echo "[ccdream] no eligible projects discovered"

  for project in "${PROJECTS[@]}"; do
    [ -z "${project}" ] && continue
    echo "--- project: ${project}"

    if ! timeout 600 python3 "${PLUGIN_ROOT}/scripts/dream_run.py" --project "${project}"; then
      echo "[ccdream] dream_run FAILED for ${project}"; any_failed=1; continue
    fi
    if ! timeout 600 python3 "${PLUGIN_ROOT}/scripts/auto_apply.py" --project "${project}"; then
      echo "[ccdream] auto_apply FAILED for ${project}"; any_failed=1; continue
    fi
  done

  if [ "${any_failed}" -eq 0 ]; then
    echo "${TODAY}" > "${STAMP}"
    rm -f "${FAIL_FLAG}"
    echo "=== ccdream daily run: success ==="
  else
    touch "${FAIL_FLAG}"
    echo "=== ccdream daily run: finished with failures ==="
  fi
} 2>&1 | tee -a "${LOG_FILE}"
