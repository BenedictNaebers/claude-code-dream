# ccdream

A Claude Code plugin that re-implements the removed **Dream feature** from Claude Code's auto-memory system. Once a day, it reads recent Claude Code sessions, proposes updates to the long-term memory files Claude Code already maintains, applies the confident ones automatically, and queues the rest for you to decide.

## What it does

1. **Triggers automatically.** A `SessionStart` hook fires once per day (the first Claude Code session you open wins). A stamp file prevents double-runs; a lockfile prevents concurrent starts.
2. **Discovers projects.** Any project under `~/.claude/projects/` with a non-empty `memory/` directory is dreamed about. Add `.dream-opt-out` inside a project's memory dir to skip it.
3. **Runs the dream agent.** For each project, it filters the last 3 days of sessions, renders the dream prompt, and asks `claude -p --model sonnet` (`cwd` is the project so auto-memory injects `MEMORY.md`) to produce a structured report of proposed additions, updates, and pruning candidates with per-item confidence ratings.
4. **Auto-applies the confident items.** Additions and Updates marked `Confidence: high` are applied directly to the project's memory files by a second `claude -p` call. Pruning is never auto-applied — removing memory is destructive and always human-reviewed.
5. **Queues the rest for review.** Medium/low-confidence items and pruning candidates marked `review?` go into `~/dream/pending/<slug>/<date>.md`. Walk through them interactively with `/dream-review` from inside the project.

Nothing happens in the foreground, nothing blocks session startup, and no memory file is edited without either (a) a high-confidence signal from the dream agent or (b) your explicit decision in `/dream-review`.

## Install

This repo is its own marketplace. From inside Claude Code:

```
/plugin marketplace add BenedictNaebers/claude-code-dream
/plugin install ccdream@claude-code-dream
```

Run `/reload-plugins` (or restart Claude Code) so the `SessionStart` hook registers. The next interactive session that day fires the first run.

### Updating

When a new version lands on `main`:

```
/plugin marketplace update claude-code-dream
/plugin update ccdream@claude-code-dream
```

### Local-dev install (for testing before publishing a change)

```bash
claude --plugin-dir /path/to/your/clone/claude-code-dream
```

## User-facing commands

- `/ccdream:dream-status` — last run date, in-progress state, per-project pending counts, oldest pending age. (All plugin commands are namespaced with `/ccdream:`.)
- `/ccdream:dream-run-now` — force a run immediately in the foreground, streaming progress. Useful for testing.
- `/dream-review` — interactive walkthrough of the current project's pending items. Invoked from inside the project directory. (Skill, not namespaced.)

## Status-line integration (optional)

The plugin ships `scripts/status_line.sh` — a compact snippet that prints `⏳ dream: <slug>` while the worker is running, `⚠ dream failed` if the last run errored, and nothing when idle. Wire it into `~/.claude/settings.json` however fits your existing setup.

**Standalone** (ccdream-only status line):

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash \"${HOME}/.claude/plugins/cache/claude-code-dream/ccdream/*/scripts/status_line.sh\"",
    "refreshInterval": 3000
  }
}
```

**Composed with an existing status-line script**: have your script append the snippet's output:

```bash
# inside your existing statusLine script, at the end:
snippet=$(bash "$HOME"/.claude/plugins/cache/claude-code-dream/ccdream/*/scripts/status_line.sh)
[ -n "$snippet" ] && printf ' | %s' "$snippet"
```

Version-glob (`ccdream/*/`) means you don't have to update the path when the plugin version bumps.

## Data layout

```
~/dream/
  inbox/<slug>/<date>.txt      # filtered transcript the agent read
  reports/<slug>/<date>.md     # today's report, pre auto-apply
  pending/<slug>/<date>.md     # items the autonomous path left for /dream-review
  applied/<slug>/<date>.md     # reports after auto-apply archived them
  logs/daily/<date>.log        # daily orchestrator log
  logs/<slug>/<date>.log       # per-project dream-run log
  .last_run_date               # ISO date stamp to dedupe same-day re-fires
  .last_run_failed             # present iff the last run had any project-level failure
  .run.lock                    # atomic lock directory; held while a run is in flight
```

Memory files themselves live where Claude Code's auto-memory writes them: `~/.claude/projects/<encoded>/memory/`. The plugin only writes under `~/dream/` and that memory directory.

## Opting a project out

```
touch ~/.claude/projects/<encoded>/memory/.dream-opt-out
```

The `<encoded>` segment is the project's absolute path with `/` and `.` replaced by `-`. If you're not sure, `ls ~/.claude/projects/` and pick the entry matching your project.

## Configuration

### Lookback window

By default the dream agent reads the last **3 days** of sessions per project. Longer windows catch signals from days you skipped (weekends, time off); the tradeoff is higher Sonnet cost and latency per run. Overlap is safe — the dream prompt's `## Duplicates / already captured` section flags things already in memory and `auto_apply` ignores them — but not free.

Override by setting `CCDREAM_LOOKBACK_DAYS` in the `env` block of `~/.claude/settings.json`:

```jsonc
{
  "env": {
    "CCDREAM_LOOKBACK_DAYS": "7"
  }
}
```

Valid range: 1–30 (enforced by `dream_run.py`; values outside fail the per-project run). When set, the daily log prints `lookback override: <N>d` on the first line so you know it took effect.

One-off override (e.g. catching up after vacation without editing settings):

```
/ccdream:dream-run-now 14
```

The argument is a one-shot `CCDREAM_LOOKBACK_DAYS` for that single foreground run.

## Model

Sonnet. Reading filtered transcripts and producing a structured report is well within Sonnet's range; Opus would burn Opus-specific usage limits for no quality gain.

## License

MIT.
