#!/usr/bin/env python3
"""Apply a reviewed dream report: execute `[x]` items, archive the report.

Usage:
    apply_dream.py --project <abs-path>
    apply_dream.py --project <abs-path> --report <file.md>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from dream_run import (
    CLAUDE_BIN,
    CLAUDE_FLAGS,
    DREAM_ROOT,
    HERE,
    REPORT_ROOT,
    encoded_project_dir,
    log,
)

APPLY_PROMPT = HERE.parent / "prompts" / "apply-prompt.md"
APPLIED_ROOT = DREAM_ROOT / "applied"

_CHECKED_RE = re.compile(r"^\s*-\s*\[[xX]\]", re.MULTILINE)


def has_checked_items(report_path: Path) -> bool:
    return bool(_CHECKED_RE.search(report_path.read_text()))


def resolve_target(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve (project_path, report_path) from parsed CLI args."""
    project_path = Path(args.project).expanduser().resolve()
    slug = project_path.name
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        if not report_path.exists():
            sys.exit(f"report not found: {report_path}")
        return project_path, report_path

    report_dir = REPORT_ROOT / slug
    reports = sorted(report_dir.glob("*.md"))
    if not reports:
        sys.exit(f"no dream reports in {report_dir}")
    return project_path, reports[-1]


def main() -> None:
    if not APPLY_PROMPT.exists():
        sys.exit(f"apply prompt not found: {APPLY_PROMPT}")

    ap = argparse.ArgumentParser(description="Apply a reviewed dream report")
    ap.add_argument("--project", required=True, help="Absolute project path")
    ap.add_argument("--report", help="Specific report file; defaults to latest for project")
    args = ap.parse_args()

    project_path, report_path = resolve_target(args)
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
