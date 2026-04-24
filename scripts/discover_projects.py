#!/usr/bin/env python3
"""Emit one absolute project path per line: each ~/.claude/projects/<enc>/ entry
whose line-2 cwd resolves to an existing dir with usable memory/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def warn(msg: str) -> None:
    print(f"[discover_projects] {msg}", file=sys.stderr)


def project_cwd(project_dir: Path) -> Path | None:
    """Read the newest session .jsonl and return the first `cwd` we find.

    Line 1 is a meta record (sessionId/type/permissionMode). Line 2 is
    sometimes a snapshot-update record without cwd. User/assistant content
    records carry cwd — scan forward until we find one.
    """
    jsonls = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not jsonls:
        return None
    newest = jsonls[-1]
    try:
        with newest.open() as f:
            for i, line in enumerate(f, 1):
                if i > 50:
                    break
                try:
                    cwd = json.loads(line).get("cwd")
                except json.JSONDecodeError:
                    continue
                if cwd:
                    return Path(cwd)
    except OSError as e:
        warn(f"{project_dir.name}: cannot read {newest.name}: {e}")
        return None
    warn(f"{project_dir.name}: no cwd found in first 50 lines of {newest.name}")
    return None


def memory_usable(project_dir: Path) -> bool:
    """project_dir is the ~/.claude/projects/<encoded>/ directory; that's where
    auto-memory writes. We don't need to re-encode the cwd."""
    mem = project_dir / "memory"
    if not mem.is_dir():
        return False
    if (mem / ".dream-opt-out").exists():
        return False
    return (mem / "MEMORY.md").exists() or any(mem.glob("*.md"))


def main() -> int:
    if not CLAUDE_PROJECTS.is_dir():
        return 0
    seen_slugs: dict[str, Path] = {}
    for project_dir in sorted(CLAUDE_PROJECTS.iterdir()):
        if not project_dir.is_dir():
            continue
        if not memory_usable(project_dir):
            continue
        cwd = project_cwd(project_dir)
        if cwd is None or not cwd.is_dir():
            continue
        slug = cwd.name
        if slug in seen_slugs:
            warn(
                f"slug collision: '{slug}' at {cwd} conflicts with "
                f"{seen_slugs[slug]} — skipping second"
            )
            continue
        seen_slugs[slug] = cwd
        print(str(cwd.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
