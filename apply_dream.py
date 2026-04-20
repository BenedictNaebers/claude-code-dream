#!/usr/bin/env python3
"""Apply a reviewed dream report: execute `[x]` items, archive the report.

Usage:
    apply_dream.py                           # latest report, only if PROJECTS has one entry
    apply_dream.py <project-name>            # latest report for that project
    apply_dream.py <path/to/report.md>       # a specific report
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from dream_run import (
    CLAUDE_BIN,
    CLAUDE_FLAGS,
    DREAM_ROOT,
    HERE,
    PROJECTS,
    REPORT_ROOT,
    encoded_project_dir,
    log,
)

APPLY_PROMPT = HERE / "apply-prompt.md"
APPLIED_ROOT = DREAM_ROOT / "applied"

_CHECKED_RE = re.compile(r"^\s*-\s*\[[xX]\]", re.MULTILINE)


def has_checked_items(report_path: Path) -> bool:
    return bool(_CHECKED_RE.search(report_path.read_text()))


def find_project_by_slug(slug: str) -> Path:
    for p in PROJECTS:
        path = Path(p)
        if path.name == slug or str(path) == slug:
            return path
    sys.exit(f"project '{slug}' not in PROJECTS")


def resolve_target(arg: str | None) -> tuple[Path, Path]:
    """Resolve (project_path, report_path) from the CLI argument."""
    if arg and arg.endswith(".md"):
        report_path = Path(arg).expanduser().resolve()
        if not report_path.exists():
            sys.exit(f"report not found: {report_path}")
        project_path = find_project_by_slug(report_path.parent.name)
        return project_path, report_path

    if arg:
        project_path = find_project_by_slug(arg)
    elif len(PROJECTS) == 1:
        project_path = Path(PROJECTS[0])
    else:
        sys.exit("multiple projects configured — pass a project name or report path")

    report_dir = REPORT_ROOT / project_path.name
    reports = sorted(report_dir.glob("*.md"))
    if not reports:
        sys.exit(f"no dream reports in {report_dir}")
    return project_path, reports[-1]


def main() -> None:
    if not APPLY_PROMPT.exists():
        sys.exit(f"apply prompt not found: {APPLY_PROMPT}")

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    project_path, report_path = resolve_target(arg)
    slug = project_path.name

    if not has_checked_items(report_path):
        log(slug, f"no [x] items in {report_path.name}, skipping")
        return

    applied_dir = APPLIED_ROOT / slug
    applied_dir.mkdir(parents=True, exist_ok=True)

    memory_path = encoded_project_dir(project_path) / "memory"

    prompt = (
        APPLY_PROMPT.read_text()
        .replace("{{REPORT_PATH}}", str(report_path))
        .replace("{{MEMORY_PATH}}", str(memory_path))
        .replace("{{APPLIED_DIR}}", str(applied_dir))
    )

    log(slug, f"applying {report_path.name}")
    # Let stdout stream to the terminal so the user sees progress live.
    result = subprocess.run(
        [CLAUDE_BIN, "-p", *CLAUDE_FLAGS],
        input=prompt,
        text=True,
        cwd=str(project_path),
        check=False,
    )
    if result.returncode != 0:
        log(slug, f"claude -p exited {result.returncode}")


if __name__ == "__main__":
    main()
