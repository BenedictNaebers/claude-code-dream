---
name: dream-discuss
description: Use when the user wants to walk through the "review?" items in a dream report interactively — items the dream agent flagged as needing judgment that the batch applier cannot resolve on its own. Loads the latest dream report for the current project, shows only the items that need a human decision, discusses each with the user, and applies the agreed changes to memory.
---

# Dream Discuss & Apply

## Purpose

The batch `apply_dream.py` applier executes `[x]` items mechanically. It deliberately **skips** two kinds of items even when checked:

- Pruning items marked `review?` — the dream agent was unsure and wants human judgment.
- Any item whose instructions are ambiguous — the applier refuses rather than guess.

This skill is the interactive counterpart: surface just those items, talk them through with the user, then apply whatever the user decides.

## Inputs (derive, do not ask)

- **Current project slug**: `basename "$PWD"`.
- **Report directory**: `~/dream/reports/<slug>/`.
- **Target report**: the lexicographically latest `*.md` in that directory (filenames are ISO dates). If there is none, tell the user and stop.
- **Memory directory**: already known via the auto-memory section of your system prompt — edit those files directly. Do not write anywhere else.

If the user passes a specific path or date (`/dream-discuss 2026-04-18` or a full path), honour it instead of the latest.

## Workflow

### 1. Locate and scope

Read the report. Extract **only** the items that need discussion:

- Every line in `## Pruning candidates` whose action ends with `review?`.
- Any `[x]` or `[ ]` item anywhere in the report whose **Proposed** text is vague, conditional, or self-contradictory (the kind of item the batch applier would skip as ambiguous).
- Anything the user explicitly asks about after you present the list.

Ignore clean `[x]` items (the batch applier handles those) and clean `[ ]` items (the user already rejected them). Do not re-litigate decisions the user has already made.

### 2. Present

Show a compact numbered list of the review items — one line each: file, reason, proposed action. Do **not** dump the whole report. Then ask the user what they want to do. Typical answers:

- "apply 1 and 3, skip 2"
- "remove file X instead of archiving"
- "1 — show me the file first"

### 3. Discuss, one item at a time

For each item the user wants to discuss:

- Read the relevant memory file(s) so you can answer concretely.
- Summarise the situation in 1–3 sentences: what exists now, what the report proposes, why it was flagged for review.
- Offer the realistic options (remove / trim section / archive / update / leave). Recommend one if the evidence is clear; say "I'd pick either" if it isn't.
- Wait for the user's decision before touching any file.

Keep this tight. The user is here to decide, not to read essays.

### 4. Apply

Once the user has decided on an item, apply it immediately using the same rules the batch applier follows (see `apply-prompt.md` in the dream feature repo if in doubt):

- **remove**: delete the memory file; remove its line from `MEMORY.md`.
- **trim section "<name>"**: edit the file in place; keep frontmatter and other sections intact. Update the `MEMORY.md` hook line only if the file's description changes.
- **archive**: move the file to `<memory>/archive/<file>` (create `archive/` if missing); remove its line from `MEMORY.md`.
- **update**: edit the file per the user's instruction. If the description changes, update frontmatter and the `MEMORY.md` hook line.
- **leave / skip**: no file changes.

Match the existing memory file style (short, one-line claim + **Why:** + **How to apply:** for feedback/project types). Don't paste verbose report prose into memory files.

### 5. Record in the report

After each applied item, edit the report line so the next batch-apply run does not re-raise it:

- Change `[ ]` → `[x]` and replace `review?` with the action taken: `remove`, `archive`, `trim section: "<name>"`, or `update`.
- For items the user consciously rejected during discussion, change `[ ]` → `[skip]` so the dream agent stops re-proposing them.
- Leave truly undecided items untouched; the user can come back later.

Do **not** move the report to `applied/` — that is the batch applier's job, and unresolved `[x]` items elsewhere in the report may still need it to run.

### 6. Summary

When the user is done (or says "that's all"), print a terse summary: count applied / skipped / left-for-later, plus any file you archived or removed. No other output.

## Rules

- Only act on items the user explicitly approves this turn. Never batch-apply the whole review list on your own initiative.
- Only touch files in the memory directory and the report itself. Do not write anywhere else.
- If you're unsure what the user meant, ask — this skill is interactive by design.
- If the report has no review-worthy items, say so in one line and stop. Don't invent work.
