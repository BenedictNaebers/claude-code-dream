---
description: Force a dream run now (foreground, streaming output). Useful for testing.
---

# Dream Run Now

Execute the daily runner in the foreground so the user sees progress live.

1. If `~/dream/.last_run_date` equals today's ISO date, ask the user: "Already ran today — re-run anyway?" and wait for confirmation.
2. If the user supplied arguments to the slash command (e.g. `/ccdream:dream-run-now 14`), treat the first numeric argument as a one-shot lookback override and export it: `export CCDREAM_LOOKBACK_DAYS=<N>`. If no argument, do not touch the variable; the runner falls back to its default (3 days) or whatever is set in settings.json `env`.
3. `rm -f ~/dream/.last_run_date`.
4. `rmdir ~/dream/.run.lock 2>/dev/null || true` (clear any stale lock).
5. Invoke `bash "${CLAUDE_PLUGIN_ROOT}/scripts/daily_run.sh"` in the foreground, streaming its output.
6. When it finishes, print the last 20 lines of `~/dream/logs/daily/$(date +%F).log`.

Do NOT background. Do NOT exit until the runner exits.
