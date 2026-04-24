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

```
/plugin install /Users/benedict.naebers/Projects/CCDreamFeature
```

Or from a git remote:

```
/plugin install <repo-url>
```

Restart Claude Code so the `SessionStart` hook registers. The next interactive session that day fires the first run.

## User-facing commands

- `/dream-status` — last run date, failure flag, per-project pending counts, oldest pending age.
- `/dream-run-now` — force a run immediately in the foreground, streaming progress. Useful for testing.
- `/dream-review` — interactive walkthrough of the current project's pending items. Invoked from inside the project directory.

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

## Model

Sonnet. Reading filtered transcripts and producing a structured report is well within Sonnet's range; Opus would burn Opus-specific usage limits for no quality gain.

## License

MIT.
