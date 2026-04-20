#!/usr/bin/env python3
"""Nightly dream-agent runner.

For each configured project:
  1. Filter recent session logs via filter_session.py -> inbox file.
  2. Render dream-prompt.md with substituted paths.
  3. Invoke `claude -p` with cwd set to the project so auto-memory injects.
  4. Log stdout/stderr; the report is written by Claude to REPORT_PATH.

Intended to be triggered by launchd / Task Scheduler once per day.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

# --- Configuration -----------------------------------------------------------

# Projects to analyse. One dream report per project, per run.
PROJECTS: list[str] = [
    "/Users/benedict.naebers/Projects/world-insight-wision",
    # add more absolute project paths here
]

# Include sessions modified within the last N days.
LOOKBACK_DAYS = 3

# Permission mode for the headless claude run. The dream prompt explicitly
# restricts writes to the report path, so bypassPermissions is the expected
# default for unattended runs. Change this if you prefer stricter behaviour.
#
# Model: Sonnet is sufficient for reading filtered transcripts and producing a
# structured report. Opus is overkill and eats Opus-specific usage limits.
CLAUDE_FLAGS: list[str] = [
    "--permission-mode", "bypassPermissions",
    "--model", "sonnet",
]

# Override with CLAUDE_BIN env var if `claude` isn't on PATH.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

# --- Paths (derived) ---------------------------------------------------------

HERE = Path(__file__).parent.resolve()
FILTER_SCRIPT = HERE / "filter_session.py"
PROMPT_TEMPLATE = HERE / "dream-prompt.md"

# Kept outside ~/.claude/ because Claude Code sandboxes writes to that path.
DREAM_ROOT = Path.home() / "dream"
INBOX_ROOT = DREAM_ROOT / "inbox"
REPORT_ROOT = DREAM_ROOT / "reports"
LOG_ROOT = DREAM_ROOT / "logs"

# --- Helpers -----------------------------------------------------------------


def encoded_project_dir(project_path: Path) -> Path:
    """Mirror Claude Code's encoding of cwd -> session-log directory name.

    Claude Code replaces both `/` and `.` with `-`, so paths containing dots
    (e.g. usernames like `first.last`) need both substitutions.
    """
    encoded = str(project_path.resolve()).replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / encoded


DREAM_MARKER = "DREAM_AGENT_RUN: do-not-ingest"
# Fallback for dream sessions that ran before the marker was introduced.
DREAM_FALLBACK_NEEDLE = b"# Dream Agent"


def is_dream_session(path: Path) -> bool:
    """Dream runs tag their prompt with a marker so we can skip them next time."""
    try:
        with path.open("rb") as f:
            head = f.read(16384)
    except OSError:
        return False
    return DREAM_MARKER.encode() in head or DREAM_FALLBACK_NEEDLE in head


def recent_sessions(project_path: Path, lookback_days: int) -> list[Path]:
    session_dir = encoded_project_dir(project_path)
    if not session_dir.is_dir():
        return []
    cutoff = dt.datetime.now().timestamp() - lookback_days * 86400
    return sorted(
        p
        for p in session_dir.glob("*.jsonl")
        if p.stat().st_mtime >= cutoff and not is_dream_session(p)
    )


def render_prompt(
    template: str, input_path: Path, report_path: Path, memory_path: Path
) -> str:
    return (
        template.replace("{{INPUT_PATH}}", str(input_path))
        .replace("{{REPORT_PATH}}", str(report_path))
        .replace("{{MEMORY_PATH}}", str(memory_path))
    )


def log(slug: str, msg: str) -> None:
    print(f"[{slug}] {msg}", file=sys.stderr)


# --- Per-project run ---------------------------------------------------------


def run_for_project(project_path: Path, date_str: str) -> None:
    slug = project_path.name
    log(slug, "starting")

    if not project_path.is_dir():
        log(slug, "project dir missing, skipping")
        return

    sessions = recent_sessions(project_path, LOOKBACK_DAYS)
    if not sessions:
        log(slug, f"no sessions in last {LOOKBACK_DAYS}d, skipping")
        return

    inbox_dir = INBOX_ROOT / slug
    report_dir = REPORT_ROOT / slug
    log_dir = LOG_ROOT / slug
    for d in (inbox_dir, report_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    input_path = inbox_dir / f"{date_str}.txt"
    report_path = report_dir / f"{date_str}.md"
    log_path = log_dir / f"{date_str}.log"

    # 1. Filter.
    with input_path.open("w") as f:
        subprocess.run(
            [sys.executable, str(FILTER_SCRIPT), *map(str, sessions)],
            check=True,
            stdout=f,
        )
    log(slug, f"filtered {len(sessions)} session(s) -> {input_path}")

    # 2. Render prompt.
    memory_path = encoded_project_dir(project_path) / "memory"
    template = PROMPT_TEMPLATE.read_text()
    prompt = render_prompt(template, input_path, report_path, memory_path)

    # 3. Invoke claude -p. cwd = project so auto-memory context injects.
    cmd = [CLAUDE_BIN, "-p", *CLAUDE_FLAGS]
    with log_path.open("w") as logfile:
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            cwd=str(project_path),
            stdout=logfile,
            stderr=subprocess.STDOUT,
            check=False,
        )

    if result.returncode != 0:
        log(slug, f"claude -p exited {result.returncode}; see {log_path}")
        return

    if not report_path.exists():
        log(slug, f"claude -p finished but no report at {report_path}; see {log_path}")
        return

    log(slug, f"done -> {report_path}")


# --- Entry point -------------------------------------------------------------


def main() -> None:
    if not FILTER_SCRIPT.exists():
        sys.exit(f"filter script not found: {FILTER_SCRIPT}")
    if not PROMPT_TEMPLATE.exists():
        sys.exit(f"prompt template not found: {PROMPT_TEMPLATE}")

    date_str = dt.date.today().isoformat()
    for project in PROJECTS:
        run_for_project(Path(project), date_str)


if __name__ == "__main__":
    main()
