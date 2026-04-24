---
description: Show status of the nightly dream agent (last run, failures, pending review items).
---

# Dream Status

Print a one-screen summary. Do not run long-running tools.

1. Read `~/dream/.last_run_date` if it exists. Print `Last run: <date>` or `Last run: never`.
2. If `~/dream/.last_run_failed` exists, print `Last run: FAILED — see ~/dream/logs/daily/<latest>.log` naming the newest file there.
3. List dirs under `~/dream/pending/`. For each `<slug>/` with ≥1 `*.md`:
   - Count the files.
   - Find the oldest by mtime; compute age in days.
   - Print: `<slug>: <N> pending, oldest <age>d`.
4. If `~/dream/pending/` is empty or absent, print `No pending review items.`
5. Final line: `Use /dream-review in a project directory to walk through its pending items.`

Terse. One line per fact. No tables.
