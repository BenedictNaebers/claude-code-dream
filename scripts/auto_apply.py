#!/usr/bin/env python3
"""Post-process today's dream report.

- Auto-apply Additions/Updates with Confidence: high (via apply_dream.py).
- Route everything else (medium/low + pruning `review?`) to
  ~/dream/pending/<slug>/<date>.md for /dream-review to pick up.

Pruning items are never auto-applied — even at high confidence. Removing
memory is more destructive than adding it; humans decide.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
DREAM_ROOT = Path.home() / "dream"
REPORT_ROOT = DREAM_ROOT / "reports"
PENDING_ROOT = DREAM_ROOT / "pending"
APPLIED_ROOT = DREAM_ROOT / "applied"
APPLY_DREAM = HERE / "apply_dream.py"

SECTION_RE = re.compile(r"^(#{1,6})\s+(.+)$")
ITEM_RE = re.compile(r"^-\s+\[( |x|X|skip)\]")
CONFIDENCE_RE = re.compile(r"\*\*Confidence:\*\*\s*(\w+)", re.IGNORECASE)
PRUNING_ACTION_RE = re.compile(
    r"—\s*(remove|trim section[^—]*|archive|review\?)\s*$", re.IGNORECASE
)


class Block:
    __slots__ = ("kind", "section", "subsection", "lines")

    def __init__(self, kind, section, subsection, lines):
        self.kind = kind
        self.section = section
        self.subsection = subsection
        self.lines = lines

    def text(self) -> str:
        return "\n".join(self.lines)

    def confidence(self) -> str | None:
        m = CONFIDENCE_RE.search(self.text())
        return m.group(1).lower() if m else None

    def pruning_action(self) -> str | None:
        m = PRUNING_ACTION_RE.search(self.lines[0])
        return m.group(1).lower() if m else None


def parse(report_text: str) -> list[Block]:
    """Block-wise parser. An item block is `- [ ]` + indented continuations
    until the next sibling `- [ ]` or non-indented non-blank line."""
    blocks: list[Block] = []
    section = subsection = None
    buf: list[str] = []
    buf_is_item = False

    def flush():
        if buf:
            blocks.append(
                Block("item" if buf_is_item else "other", section, subsection, buf[:])
            )
            buf.clear()

    for raw in report_text.splitlines():
        m = SECTION_RE.match(raw)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            if level <= 2:
                section, subsection = title, None
            elif level == 3:
                subsection = title
            buf_is_item = False
            buf.append(raw)
            continue
        if ITEM_RE.match(raw):
            flush()
            buf_is_item = True
            buf.append(raw)
            continue
        if buf_is_item:
            # Continuations: indented, blank, or a **Key:** line.
            if (
                raw.startswith((" ", "\t"))
                or raw.strip() == ""
                or raw.strip().startswith("**")
            ):
                buf.append(raw)
                continue
            flush()
            buf_is_item = False
        buf.append(raw)
    flush()
    return blocks


def is_ambiguous(block: Block) -> bool:
    """Conservative — err toward NOT auto-applying."""
    t = block.text().lower()
    if any(kw in t for kw in ("ambiguous", "unsure", "not sure")):
        return True
    if block.subsection == "Additions" and "file:" not in t:
        return True
    if block.subsection == "Updates" and "**proposed:**" not in t:
        return True
    return False


def tick(block: Block) -> None:
    block.lines[0] = re.sub(r"-\s+\[ \]", "- [x]", block.lines[0], count=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    project_path = Path(args.project).resolve()
    slug = project_path.name
    today = dt.date.today().isoformat()
    report_path = REPORT_ROOT / slug / f"{today}.md"
    if not report_path.exists():
        print(f"[auto_apply] no report at {report_path}; nothing to do")
        return 0

    blocks = parse(report_path.read_text())
    auto_count = 0
    pending: dict[str, list[Block]] = {
        "Additions": [],
        "Updates": [],
        "Pruning": [],
    }

    for b in blocks:
        if b.kind != "item":
            continue
        if b.section == "Proposed memory changes" and b.subsection in (
            "Additions",
            "Updates",
        ):
            if b.confidence() == "high" and not is_ambiguous(b):
                tick(b)
                auto_count += 1
            else:
                pending[b.subsection].append(b)
        elif b.section == "Pruning candidates":
            # Never auto-apply pruning. review? goes to pending; everything else
            # stays in the report and is archived untouched.
            if b.pruning_action() == "review?":
                pending["Pruning"].append(b)

    modified_report_text = "\n".join(line for b in blocks for line in b.lines) + "\n"

    applied_dir = APPLIED_ROOT / slug
    applied_dir.mkdir(parents=True, exist_ok=True)
    pending_dir = PENDING_ROOT / slug
    pending_dir.mkdir(parents=True, exist_ok=True)

    if any(pending.values()):
        out: list[str] = [
            f"# Dream Pending — {today}",
            f"(carried over from report {today}.md)",
            "",
        ]
        if pending["Additions"] or pending["Updates"]:
            out += ["## Proposed memory changes", ""]
            if pending["Additions"]:
                out.append("### Additions")
                for b in pending["Additions"]:
                    out.append(b.text())
                out.append("")
            if pending["Updates"]:
                out.append("### Updates")
                for b in pending["Updates"]:
                    out.append(b.text())
                out.append("")
        if pending["Pruning"]:
            out.append("## Pruning candidates")
            for b in pending["Pruning"]:
                out.append(b.text())
            out.append("")
        (pending_dir / f"{today}.md").write_text("\n".join(out))
        print(f"[auto_apply] wrote {pending_dir / (today + '.md')}")

    if auto_count > 0:
        # Overwrite report in place with ticked items. apply_dream moves it to
        # applied/<slug>/<date>.md via the apply-prompt — clean archive name.
        report_path.write_text(modified_report_text)
        result = subprocess.run(
            [
                sys.executable,
                str(APPLY_DREAM),
                "--project",
                str(project_path),
                "--report",
                str(report_path),
            ],
            check=False,
        )
        if result.returncode != 0:
            print(
                f"[auto_apply] apply_dream exited {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode
    else:
        shutil.move(str(report_path), str(applied_dir / f"{today}.md"))
        print("[auto_apply] no high-confidence items; archived report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
