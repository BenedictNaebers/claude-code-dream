#!/usr/bin/env python3
"""Compact a Claude Code session .jsonl into a transcript for the dream agent.

Usage:
    python3 filter_session.py path/to/session.jsonl [more.jsonl ...]

Outputs a plain-text transcript to stdout. Drops harness metadata, collapses
tool calls to one line, and truncates tool results.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Session logs store only the encrypted signature for thinking blocks, not the
# plaintext reasoning. Including them just emits empty `[THINKING]` headers.
INCLUDE_THINKING = False

TOOL_RESULT_HEAD = 200
TOOL_RESULT_TAIL = 200

DROP_TYPES = {
    "permission-mode",
    "file-history-snapshot",
    "last-prompt",
    "custom-title",
    "agent-name",
    "system",
    "attachment",
}

_CMD_NAME_RE = re.compile(r"<command-name>([^<]+)</command-name>")
_CMD_ARGS_RE = re.compile(r"<command-args>([^<]*)</command-args>")


def classify_user_text(text: str) -> tuple[str, str]:
    """Return (kind, rendered) for a user text block.

    kind is one of:
      - "skip":    drop entirely
      - "cmd":     emit rendered as a single `[CMD ...]` line
      - "text":    emit as a normal [USER] block using rendered as the content
    """
    stripped = text.strip()
    if stripped.startswith("<local-command-caveat>") or stripped.startswith(
        "<local-command-stdout>"
    ):
        return ("skip", "")
    if stripped.startswith("<command-name>"):
        name_match = _CMD_NAME_RE.search(stripped)
        args_match = _CMD_ARGS_RE.search(stripped)
        name = name_match.group(1) if name_match else "?"
        args = args_match.group(1).strip() if args_match else ""
        formatted = f"[CMD {name} {args}]" if args else f"[CMD {name}]"
        return ("cmd", formatted)
    return ("text", text)


def summarise_tool_use(name: str, inp: object) -> str:
    if not isinstance(inp, dict):
        return name
    if name == "Bash":
        return f"Bash: {str(inp.get('command', ''))[:200]}"
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        return f"{name} {inp.get('file_path', '')}"
    if name == "Grep":
        loc = f" in {inp['path']}" if inp.get("path") else ""
        return f"Grep {inp.get('pattern', '')!r}{loc}"
    if name == "Glob":
        return f"Glob {inp.get('pattern', '')}"
    if name == "Agent":
        sub = inp.get("subagent_type", "general-purpose")
        return f"Agent[{sub}]: {inp.get('description', '')}"
    if name == "WebFetch":
        return f"WebFetch {inp.get('url', '')}"
    if name == "WebSearch":
        return f"WebSearch {inp.get('query', '')!r}"
    if name == "Skill":
        return f"Skill {inp.get('skill', '')}"
    if name.startswith("Task"):
        return f"{name}: {inp.get('description') or inp.get('content') or ''}"
    short = json.dumps(inp, default=str)[:120]
    return f"{name} {short}"


def summarise_tool_result(content: object, is_error: bool) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "image":
                    parts.append("[image]")
                else:
                    parts.append(json.dumps(b, default=str))
            else:
                parts.append(str(b))
        text = "\n".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, default=str)

    marker = "ERROR" if is_error else "ok"
    if len(text) <= TOOL_RESULT_HEAD + TOOL_RESULT_TAIL + 50:
        return f"[{marker}] {text.strip()}"
    head = text[:TOOL_RESULT_HEAD]
    tail = text[-TOOL_RESULT_TAIL:]
    dropped = len(text) - TOOL_RESULT_HEAD - TOOL_RESULT_TAIL
    return f"[{marker}] {head}\n…[{dropped} chars truncated]…\n{tail}"


def _render_user_text(text: str) -> str | None:
    kind, rendered = classify_user_text(text)
    if kind == "skip":
        return None
    if kind == "cmd":
        return rendered
    return f"\n[USER]\n{rendered}"


def filter_session(path: Path) -> tuple[str | None, str]:
    out: list[str] = []
    first_ts: str | None = None
    git_branch: str | None = None
    cwd: str | None = None
    session_id: str | None = None

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if session_id is None:
                session_id = obj.get("sessionId")
            if first_ts is None and obj.get("timestamp"):
                first_ts = obj["timestamp"]
            if obj.get("gitBranch"):
                git_branch = obj["gitBranch"]
            if obj.get("cwd"):
                cwd = obj["cwd"]

            t = obj.get("type")
            if t in DROP_TYPES:
                continue
            if obj.get("isCompactSummary"):
                continue

            if t == "user":
                content = obj.get("message", {}).get("content")
                if isinstance(content, str):
                    rendered = _render_user_text(content)
                    if rendered is not None:
                        out.append(rendered)
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            rendered = _render_user_text(b.get("text", ""))
                            if rendered is not None:
                                out.append(rendered)
                        elif b.get("type") == "tool_result":
                            out.append(
                                "[TOOL RESULT] "
                                + summarise_tool_result(
                                    b.get("content"), bool(b.get("is_error"))
                                )
                            )
            elif t == "assistant":
                content = obj.get("message", {}).get("content")
                if isinstance(content, str):
                    out.append(f"\n[ASSISTANT]\n{content}")
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "text":
                            out.append(f"\n[ASSISTANT]\n{b.get('text', '')}")
                        elif bt == "thinking" and INCLUDE_THINKING:
                            thought = b.get("thinking", "").strip()
                            if thought:
                                out.append(f"\n[THINKING]\n{thought}")
                        elif bt == "tool_use":
                            out.append(
                                "[TOOL] "
                                + summarise_tool_use(
                                    b.get("name", ""), b.get("input", {})
                                )
                            )

    short_id = (session_id or "?")[:8]
    header = (
        f"=== SESSION {short_id} | {first_ts or '?'} | "
        f"branch={git_branch or '?'} | cwd={cwd or '?'} ==="
    )
    return first_ts, header + "\n" + "\n".join(out)


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: filter_session.py <session.jsonl> [more.jsonl ...]",
            file=sys.stderr,
        )
        sys.exit(2)
    sessions = [filter_session(Path(p)) for p in sys.argv[1:]]
    sessions.sort(key=lambda s: s[0] or "")
    for _, text in sessions:
        print(text)
        print()


if __name__ == "__main__":
    main()
