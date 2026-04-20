# Claude Code Dream

A "dream agent" for Claude Code that reviews the past few days of your sessions, proposes updates to your project's long-term memory, and lets you approve them with a checkbox UI.

It is an external re-implementation of the old **Dream feature** that once shipped inside Claude Code's *auto memory* system — the one that ran in the background, read your recent transcripts, and suggested changes to your saved memory files. That built-in feature was removed; this project emulates its behaviour as a local cron-driven pipeline you run against your own Claude Code session logs.

## What it does

1. **Filters** your recent Claude Code session `.jsonl` logs into a compact transcript.
2. **Dreams** — invokes `claude -p` with a carefully scoped prompt that asks Claude to:
   - extract signals (deliberate decisions, corrections, validations, stated intent, external-system references, repeated friction),
   - compare them to your existing `MEMORY.md` and memory files,
   - and produce a **dry-run report** with proposed additions, updates, and pruning candidates.
3. **Reviews** — you open the report in a small local web UI, tick the checkboxes for the items you want, and leave the rest.
4. **Applies** — a second `claude -p` run edits your memory files according to the ticked items and archives the report.
5. **Discusses** — for anything the agent flagged as `review?` (judgment calls it refused to automate), you can walk through them interactively with the `dream-discuss` skill.

Nothing happens to your memory files without your explicit approval.

## What it emulates

The original Dream feature inside Claude Code's auto-memory system periodically consolidated recent conversations into memory suggestions. This repo recreates that loop as a standalone pipeline you run yourself, with three deliberate changes:

- **Dry run by default.** The dream agent writes a report, not memory edits. The applier is a separate step.
- **Per-project reports.** One project per run, one report per day, stored under `~/dream/`.
- **Review-aware.** Items the agent is unsure about are flagged `review?` and routed to the `dream-discuss` skill instead of being silently dropped or auto-applied.

## How it works

```
  session .jsonl                      ~/dream/
        │                                 │
        ▼                                 ├── inbox/<project>/<date>.txt   (filtered transcript)
  filter_session.py ──▶ transcript ─▶    ├── reports/<project>/<date>.md  (dream report, checkboxes)
                                          ├── applied/<project>/<date>.md  (report after apply)
                                          └── logs/<project>/<date>.log   (claude -p stdout)
        │
        ▼
  dream_run.py          renders dream-prompt.md ─▶ `claude -p` (cwd=project) ─▶ writes report
  apply_dream.py        renders apply-prompt.md ─▶ `claude -p` (cwd=project) ─▶ edits memory files
  dream_ui.py           Flask UI:  [Run Dream] [Apply Selections] + inline report renderer
```

Key design choices:

- **`cwd` is the project directory** when `claude -p` is invoked, so Claude Code's auto-memory injects that project's `MEMORY.md` and files into context. The dream agent reads them, the applier edits them — the same way a normal Claude Code session would.
- **Dream sessions are marked** with an `DREAM_AGENT_RUN: do-not-ingest` comment in their prompt so later dream runs skip their own session logs.
- **Scoped writes.** The dream prompt only allows writing to the report path; the apply prompt only allows writing to the memory directory and moving the report to `applied/`.
- **Sonnet, not Opus.** Reading filtered transcripts and producing a structured report is well within Sonnet's range; using Opus would burn Opus-specific usage limits for no quality gain.

Files in this repo:

| File | Role |
| --- | --- |
| `dream-prompt.md` | Prompt template for the nightly dream run |
| `apply-prompt.md` | Prompt template for applying an approved report |
| `filter_session.py` | Compacts a Claude Code session `.jsonl` into a readable transcript |
| `dream_run.py` | Orchestrator: per project, filter → render prompt → `claude -p` → report |
| `apply_dream.py` | Orchestrator: read report → `claude -p` → memory edits + archive |
| `dream_ui.py` | Local Flask UI with Run Dream / Apply Selections buttons and an inline report view |
| `skills/dream-discuss/SKILL.md` | Claude Code skill for the interactive "review?" conversation |

## How to run it

### 1. Prerequisites

- Claude Code CLI (`claude`) installed and on your `PATH` (or set `CLAUDE_BIN`).
- Python 3.10+.
- `pip install -r requirements.txt` (only Flask, for the UI).

### 2. Turn on auto memory in Claude Code

**This is required.** The dream agent operates on the memory system that Claude Code's auto-memory feature populates. If auto memory is off, there is no `MEMORY.md`, no memory files, and nothing to consolidate.

In your Claude Code user settings, enable the auto-memory setting (in recent versions it appears as an "auto memory" toggle or a `memory.autoMemory` / equivalent option in `~/.claude/settings.json`). After enabling, run at least a few normal Claude Code sessions so your project accrues some memory before you try to dream.

You can confirm it's working by checking that
`~/.claude/projects/<encoded-project-path>/memory/MEMORY.md` exists for the project you plan to analyse.

### 3. Configure projects

Edit the `PROJECTS` list near the top of `dream_run.py`:

```python
PROJECTS: list[str] = [
    "/absolute/path/to/your/project",
    # add more absolute project paths here
]
```

One entry per project you want dreamed about. Each gets its own subdirectory under `~/dream/`.

### 4. Run it manually

```bash
# generate a report (reads recent sessions, writes ~/dream/reports/<slug>/<date>.md)
python3 dream_run.py
python3 dream_run.py --lookback-days 7   # override the default 3-day window

# open the UI to tick boxes and apply
python3 dream_ui.py
#   Run Dream        -> runs dream_run.py (lookback days picker is in the toolbar)
#   Apply Selections -> runs apply_dream.py on the latest report
```

The UI has a "Lookback N days" input next to the Run Dream button; changes persist across reloads via `localStorage`. The default and allowed range come from `LOOKBACK_DAYS` / `LOOKBACK_MIN` / `LOOKBACK_MAX` in `dream_run.py`.

Or skip the UI and do it on the command line:

```bash
# edit ~/dream/reports/<slug>/<date>.md in your editor, flip `[ ]` -> `[x]`
python3 apply_dream.py <project-slug>
```

### 5. Schedule it (optional)

On macOS, wire `dream_run.py` into a launchd plist to fire once a day. On Linux, a cron entry. The runner is idempotent per day — one report per project per date.

## The `dream-discuss` skill

The batch applier is deliberately conservative. It executes ticked items mechanically and **skips two kinds of items even when ticked**:

- Pruning candidates whose action is `review?` — the dream agent wanted human judgment.
- Anything whose instructions are ambiguous or self-contradictory.

The `dream-discuss` skill is the interactive counterpart. To use it:

1. **Install the skill** into your Claude Code skills directory so Claude Code can discover it:

   ```bash
   mkdir -p ~/.claude/skills
   ln -s "$PWD/skills/dream-discuss" ~/.claude/skills/dream-discuss
   ```

   (Or copy the folder instead of symlinking if you prefer.)

2. **Open a Claude Code session** in the project you just dreamed about.

3. **Invoke it**: `/dream-discuss` — the skill will:
   - find the latest report under `~/dream/reports/<slug>/`,
   - surface **only** the review-worthy items,
   - walk through them with you one at a time,
   - apply the agreed changes to memory directly,
   - and tick the report line off so the batch applier does not re-raise it.

Use `dream-discuss` **after** you've run the batch apply — it handles the leftovers the applier deliberately did not touch. You can also pass a specific date (`/dream-discuss 2026-04-18`) to revisit an older report.

## Layout on disk

```
~/dream/
  inbox/<project-slug>/<date>.txt    # filtered transcript the agent read
  reports/<project-slug>/<date>.md   # report awaiting review / apply
  applied/<project-slug>/<date>.md   # report after batch apply archived it
  logs/<project-slug>/<date>.log     # claude -p output from that run
  logs/ui/                           # logs from UI-spawned runs
```

Memory files themselves live where Claude Code's auto-memory already puts them:
`~/.claude/projects/<encoded-project-path>/memory/`. The dream pipeline never writes outside `~/dream/` and that memory directory.

## License

MIT. Use it, fork it, break it. No warranty — this is personal tooling published in case it's useful.
