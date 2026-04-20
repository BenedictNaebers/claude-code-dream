#!/usr/bin/env python3
"""Lightweight local UI for the Dream feature.

Run:  python3 dream_ui.py            # chromeless Chrome/Edge/Brave "app window"
      python3 dream_ui.py --browser  # open in the default browser instead

Two buttons:
  - Run Dream        -> spawns dream_run.py
  - Apply Selections -> spawns apply_dream.py <project>

The latest report is rendered inline with marked.js; its task-list checkboxes
are clickable and write back to the source markdown file. A file:// link is
also exposed so you can still edit the raw .md in your editor of choice.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as dt
import re
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flask import Flask, abort, jsonify, render_template_string, request

from apply_dream import APPLIED_ROOT, _CHECKED_RE
from dream_run import (
    DREAM_ROOT,
    HERE,
    LOG_ROOT,
    LOOKBACK_DAYS,
    LOOKBACK_MAX,
    LOOKBACK_MIN,
    PROJECTS,
    REPORT_ROOT,
)

UI_LOG_ROOT = LOG_ROOT / "ui"
HOST = "127.0.0.1"
PORT = 5055

# Matches a GFM task-list item, capturing the prefix, the marker char, and the
# rest of the line. Used to flip [ ] <-> [x] in place on a single line.
_TASK_LINE_RE = re.compile(r"^(\s*-\s*\[)([ xX])(\].*)$")

app = Flask(__name__)
_lock = threading.Lock()


@dataclass
class ProcState:
    proc: Optional[subprocess.Popen] = None
    log_path: Optional[Path] = None
    returncode: Optional[int] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def _poll(self) -> None:
        if self.proc is None or self.returncode is not None:
            return
        rc = self.proc.poll()
        if rc is not None:
            self.returncode = rc
            self.finished_at = dt.datetime.now().timestamp()

    def is_running(self) -> bool:
        self._poll()
        return self.proc is not None and self.returncode is None

    def snapshot(self) -> dict:
        self._poll()
        if self.proc is None:
            state = "idle"
        elif self.returncode is None:
            state = "running"
        else:
            state = "exited"
        return {
            "state": state,
            "returncode": self.returncode,
            "log_tail": tail_log(self.log_path),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


runner = ProcState()
applier = ProcState()


def tail_log(path: Optional[Path], max_bytes: int = 8192) -> str:
    if not path or not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read()
        if size > max_bytes and b"\n" in data:
            data = data.split(b"\n", 1)[1]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def find_project(slug: str) -> Path:
    for p in PROJECTS:
        path = Path(p)
        if path.name == slug:
            return path
    abort(400, f"unknown project: {slug}")


def selected_project() -> Path:
    slug = request.args.get("project")
    if slug:
        return find_project(slug)
    return Path(PROJECTS[0])


def latest_report(project: Path) -> Optional[Path]:
    """Latest report for the project, searching the active dir and the archive.

    The applier moves processed reports from REPORT_ROOT to APPLIED_ROOT, so
    looking only in REPORT_ROOT means the UI blanks out (or regresses to an
    older report) right after a successful apply. We still want the applied
    report visible — it carries any review items the batch applier skipped and
    is the reference for cross-checking memory files.

    On filename tie (same date in both dirs — possible if dream is re-run after
    an apply), prefer the active dir: that's the one the user is working on.
    """
    active_dir = REPORT_ROOT / project.name
    applied_dir = APPLIED_ROOT / project.name
    # Iterate applied first so stable sort keeps active last on filename ties.
    candidates: list[Path] = []
    for d in (applied_dir, active_dir):
        if d.is_dir():
            candidates.extend(d.glob("*.md"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def report_snapshot(project: Path) -> dict:
    path = latest_report(project)
    if path is None:
        return {"exists": False, "path": None, "file_url": None,
                "has_checked": False, "mtime": None, "is_applied": False}
    try:
        text = path.read_text()
    except OSError:
        text = ""
    is_applied = path.parent == APPLIED_ROOT / project.name
    return {
        "exists": True,
        "path": str(path),
        "file_url": f"file://{path}",
        "has_checked": bool(_CHECKED_RE.search(text)),
        "mtime": path.stat().st_mtime,
        "is_applied": is_applied,
    }


def spawn(state: ProcState, argv: list[str], log_name: str) -> Path:
    """Start a subprocess, redirecting stdout+stderr to a fresh UI log file."""
    UI_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = UI_LOG_ROOT / log_name
    fd = log_path.open("ab")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(HERE),
            stdout=fd,
            stderr=subprocess.STDOUT,
        )
    finally:
        fd.close()
    state.proc = proc
    state.log_path = log_path
    state.returncode = None
    state.started_at = dt.datetime.now().timestamp()
    state.finished_at = None
    return log_path


# ---- Routes -----------------------------------------------------------------


@app.get("/")
def index():
    return render_template_string(
        HTML,
        multi=len(PROJECTS) > 1,
        projects=[Path(p).name for p in PROJECTS],
        default_project=Path(PROJECTS[0]).name,
        lookback_default=LOOKBACK_DAYS,
        lookback_min=LOOKBACK_MIN,
        lookback_max=LOOKBACK_MAX,
    )


@app.get("/status")
def status():
    project = selected_project()
    return jsonify({
        "project": project.name,
        "projects": [Path(p).name for p in PROJECTS],
        "runner": runner.snapshot(),
        "applier": applier.snapshot(),
        "report": report_snapshot(project),
    })


@app.post("/run")
def run():
    payload = request.get_json(force=True, silent=True) or {}
    lookback = payload.get("lookback_days", LOOKBACK_DAYS)
    try:
        lookback = int(lookback)
    except (TypeError, ValueError):
        return jsonify({"error": "lookback_days must be an integer"}), 400
    if not LOOKBACK_MIN <= lookback <= LOOKBACK_MAX:
        return jsonify({
            "error": f"lookback_days must be between {LOOKBACK_MIN} and {LOOKBACK_MAX}",
        }), 400

    with _lock:
        if runner.is_running():
            return jsonify({"error": "runner already running"}), 409
        ts = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        log_path = spawn(
            runner,
            [
                sys.executable, str(HERE / "dream_run.py"),
                "--lookback-days", str(lookback),
            ],
            f"run-{ts}.log",
        )
    return jsonify({"started": True, "log": str(log_path)}), 202


@app.post("/apply")
def apply_():
    project = selected_project()
    snap = report_snapshot(project)
    if not snap["exists"]:
        return jsonify({"error": "no report to apply — run dream first"}), 409
    if snap["is_applied"]:
        return jsonify({"error": "report already applied — run dream again for a fresh one"}), 409
    if not snap["has_checked"]:
        return jsonify({"error": "no [x] items in current report"}), 409
    with _lock:
        if runner.is_running() or applier.is_running():
            return jsonify({"error": "another script is running"}), 409
        ts = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        log_path = spawn(
            applier,
            [sys.executable, str(HERE / "apply_dream.py"), project.name],
            f"apply-{project.name}-{ts}.log",
        )
    return jsonify({"started": True, "log": str(log_path)}), 202


@app.get("/report")
def report_md():
    project = selected_project()
    path = latest_report(project)
    if path is None:
        return "", 404
    return path.read_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.post("/report/toggle")
def report_toggle():
    project = selected_project()
    path = latest_report(project)
    if path is None:
        return jsonify({"error": "no report"}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        line_idx = int(data["line"])
        checked = bool(data["checked"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "line and checked required"}), 400

    text = path.read_text()
    lines = text.split("\n")
    if not (0 <= line_idx < len(lines)):
        return jsonify({"error": "line out of range"}), 400
    m = _TASK_LINE_RE.match(lines[line_idx])
    if not m:
        return jsonify({"error": "line is not a task-list item"}), 400

    lines[line_idx] = f"{m.group(1)}{'x' if checked else ' '}{m.group(3)}"
    path.write_text("\n".join(lines))
    return jsonify({
        "ok": True,
        "mtime": path.stat().st_mtime,
        "has_checked": bool(_CHECKED_RE.search(path.read_text())),
    })


# ---- Cleanup ----------------------------------------------------------------


def _cleanup() -> None:
    for ps in (runner, applier):
        if ps.proc and ps.proc.poll() is None:
            try:
                ps.proc.terminate()
                ps.proc.wait(timeout=5)
            except Exception:
                try:
                    ps.proc.kill()
                except Exception:
                    pass


atexit.register(_cleanup)


# ---- HTML / CSS / JS --------------------------------------------------------

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dream</title>
<style>
  :root {
    --bg: #f5f6f8;
    --surface: #ffffff;
    --surface-2: #fafafb;
    --border: #e5e7eb;
    --text: #111418;
    --muted: #6b7280;
    --primary: #4f46e5;
    --primary-hover: #4338ca;
    --primary-text: #ffffff;
    --accent-warn: #f59e0b;
    --accent-ok:   #10b981;
    --accent-err:  #ef4444;
    --log-bg: #0f1115;
    --log-text: #d7dbe3;
    --shadow: 0 1px 2px rgba(0,0,0,.04), 0 4px 14px rgba(0,0,0,.06);
    --radius: 10px;
    --radius-sm: 6px;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0e0f12;
      --surface: #17181d;
      --surface-2: #1c1d23;
      --border: #2a2c33;
      --text: #e7e7ea;
      --muted: #8a8f9a;
      --primary: #7c74ff;
      --primary-hover: #9089ff;
      --log-bg: #0a0b0e;
      --log-text: #cfd3dd;
      --shadow: 0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.5);
      color-scheme: dark;
    }
  }

  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
                 Helvetica, Arial, sans-serif;
    font-size: 14px;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  .app { max-width: 960px; margin: 0 auto; padding: 24px 22px 60px; }

  header.top {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: 16px; margin-bottom: 18px;
  }
  h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
  }

  .actions {
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
    padding: 14px 16px; margin-bottom: 16px;
  }
  .actions .spacer { flex: 1; }

  button {
    font: inherit; font-weight: 500;
    padding: 8px 14px; border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--surface-2); color: var(--text);
    cursor: pointer;
    transition: background .12s ease, border-color .12s ease, transform .04s ease;
  }
  button:hover:not(:disabled) { border-color: var(--muted); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { cursor: not-allowed; opacity: .5; }
  button.primary {
    background: var(--primary); border-color: var(--primary);
    color: var(--primary-text);
  }
  button.primary:hover:not(:disabled) {
    background: var(--primary-hover); border-color: var(--primary-hover);
  }
  button.ghost {
    background: transparent; border-color: var(--border); color: var(--muted);
  }

  select, input[type=number] {
    font: inherit; padding: 6px 10px; border-radius: var(--radius-sm);
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text);
  }
  input[type=number].lookback {
    width: 64px; text-align: right;
  }
  label.field { color: var(--muted); font-size: 13px; }

  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px 3px 8px; border-radius: 999px;
    font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    border: 1px solid var(--border); background: var(--surface-2);
    color: var(--muted);
  }
  .chip .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: currentColor; opacity: .6;
  }
  .chip.s-idle    { color: var(--muted); }
  .chip.s-run     { color: var(--accent-warn); border-color: color-mix(in srgb, var(--accent-warn) 40%, var(--border)); }
  .chip.s-run .dot { animation: pulse 1.2s ease-in-out infinite; opacity: 1; }
  .chip.s-ok      { color: var(--accent-ok);   border-color: color-mix(in srgb, var(--accent-ok) 40%, var(--border));   }
  .chip.s-err     { color: var(--accent-err);  border-color: color-mix(in srgb, var(--accent-err) 40%, var(--border));  }
  @keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 1; }
    50%      { transform: scale(1.35); opacity: .55; }
  }

  details.log-card { padding: 0; overflow: hidden; margin-bottom: 16px; }
  details.log-card > summary {
    list-style: none; cursor: pointer; user-select: none;
    padding: 10px 14px; font-weight: 500;
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid transparent;
  }
  details.log-card[open] > summary { border-bottom-color: var(--border); }
  details.log-card > summary::-webkit-details-marker { display: none; }
  details.log-card > summary::before {
    content: "▸"; font-size: 10px; color: var(--muted);
    transition: transform .15s ease;
  }
  details.log-card[open] > summary::before { transform: rotate(90deg); }
  pre.log {
    margin: 0; padding: 12px 14px;
    background: var(--log-bg); color: var(--log-text);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px; line-height: 1.5;
    height: 200px; overflow-y: auto;
    white-space: pre-wrap;
  }

  .report-card { padding: 0; }
  .report-head {
    display: flex; flex-wrap: wrap; gap: 10px;
    align-items: center; justify-content: space-between;
    padding: 14px 16px; border-bottom: 1px solid var(--border);
  }
  .report-title { font-weight: 600; }
  .report-meta  { color: var(--muted); font-size: 12.5px; margin-left: 8px; }
  .report-head a {
    color: var(--primary); text-decoration: none; font-size: 13px;
    margin-right: 8px;
  }
  .report-head a:hover { text-decoration: underline; }
  .report-body {
    padding: 18px 22px 22px;
    font-size: 14px;
  }
  .report-body.muted { color: var(--muted); padding: 28px 22px; }
  .report-body h1 { font-size: 20px; margin: 0 0 10px; }
  .report-body h2 { font-size: 16px; margin: 22px 0 8px; }
  .report-body h3 { font-size: 14px; margin: 16px 0 6px; }
  .report-body p  { margin: 6px 0 10px; }
  .report-body code {
    background: var(--surface-2); padding: 1px 5px; border-radius: 4px;
    font-size: 12.5px;
  }
  .report-body pre {
    background: var(--surface-2); padding: 10px 12px;
    border-radius: 6px; overflow-x: auto;
  }
  .report-body ul { padding-left: 22px; }
  .report-body li { margin: 3px 0; }
  .report-body li.task-list-item { list-style: none; margin-left: -22px; }
  .report-body li.task-list-item input[type=checkbox] {
    margin-right: 8px; cursor: pointer; transform: translateY(1px);
    accent-color: var(--primary);
  }
  .report-body blockquote {
    border-left: 3px solid var(--border); padding: 2px 12px;
    margin: 8px 0; color: var(--muted);
  }
</style>
</head>
<body>
<div class="app">

  <header class="top">
    <div>
      <h1>Dream</h1>
      <div class="sub">Session review &middot; memory updates</div>
    </div>
    {% if multi %}
    <div>
      <label class="field" for="project">Project</label>
      <select id="project">
        {% for p in projects %}<option value="{{ p }}">{{ p }}</option>{% endfor %}
      </select>
    </div>
    {% endif %}
  </header>

  <div class="card actions">
    <button id="run" class="primary">Run Dream</button>
    <label class="field" for="lookback">Lookback</label>
    <input id="lookback" class="lookback" type="number"
           min="{{ lookback_min }}" max="{{ lookback_max }}"
           value="{{ lookback_default }}"
           title="How many days of recent session logs to analyse">
    <span class="field">days</span>
    <span id="run-chip" class="chip s-idle"><span class="dot"></span><span class="t">idle</span></span>
    <button id="apply">Apply Selections</button>
    <span id="apply-chip" class="chip s-idle"><span class="dot"></span><span class="t">idle</span></span>
    <div class="spacer"></div>
    <button id="reload-report" class="ghost" title="Re-read the report file">Reload</button>
  </div>

  <details class="card log-card" open>
    <summary>Log</summary>
    <pre class="log" id="log"></pre>
  </details>

  <div class="card report-card">
    <div class="report-head">
      <div>
        <span class="report-title" id="report-name">(no report)</span>
        <span class="report-meta"  id="report-mtime"></span>
      </div>
      <div>
        <a id="report-link" href="#" target="_blank" style="display:none">Open in editor</a>
      </div>
    </div>
    <div id="report-body" class="report-body muted">
      Run Dream to generate a report.
    </div>
  </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
const $ = (id) => document.getElementById(id);
const projectSel = $("project");
const DEFAULT_PROJECT = {{ default_project|tojson }};
const curProject = () => (projectSel ? projectSel.value : DEFAULT_PROJECT);

const LOOKBACK_MIN = {{ lookback_min }};
const LOOKBACK_MAX = {{ lookback_max }};
const LOOKBACK_DEFAULT = {{ lookback_default }};
const LOOKBACK_STORAGE_KEY = "dream.lookbackDays";

const lookbackEl = $("lookback");
const clampLookback = (n) => {
  if (!Number.isFinite(n)) return LOOKBACK_DEFAULT;
  return Math.max(LOOKBACK_MIN, Math.min(LOOKBACK_MAX, Math.round(n)));
};
try {
  const saved = parseInt(localStorage.getItem(LOOKBACK_STORAGE_KEY), 10);
  if (!Number.isNaN(saved)) lookbackEl.value = String(clampLookback(saved));
} catch {}
lookbackEl.addEventListener("change", () => {
  const v = clampLookback(parseInt(lookbackEl.value, 10));
  lookbackEl.value = String(v);
  try { localStorage.setItem(LOOKBACK_STORAGE_KEY, String(v)); } catch {}
});

async function getJSON(url) { const r = await fetch(url); return r.json(); }
async function getText(url) { const r = await fetch(url); return r.ok ? r.text() : null; }
async function postJSON(url, body) {
  const init = { method: "POST" };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const r = await fetch(url, init);
  let j = {}; try { j = await r.json(); } catch {}
  return { ok: r.ok, status: r.status, body: j };
}

function setChip(el, st) {
  el.classList.remove("s-idle", "s-run", "s-ok", "s-err");
  const t = el.querySelector(".t");
  if (st.state === "running") {
    el.classList.add("s-run"); t.textContent = "running";
  } else if (st.state === "exited") {
    const ok = st.returncode === 0;
    el.classList.add(ok ? "s-ok" : "s-err");
    t.textContent = ok ? "done" : ("exit " + st.returncode);
  } else {
    el.classList.add("s-idle"); t.textContent = "idle";
  }
}

let lastReportPath = null;
let lastReportMtime = null;

async function refreshStatus() {
  const p = curProject();
  const s = await getJSON(`/status?project=${encodeURIComponent(p)}`);
  setChip($("run-chip"),   s.runner);
  setChip($("apply-chip"), s.applier);

  let tail = "";
  if (s.runner.state === "running") tail = s.runner.log_tail;
  else if (s.applier.state === "running") tail = s.applier.log_tail;
  else tail = s.applier.log_tail || s.runner.log_tail || "";
  const logEl = $("log");
  if (logEl.textContent !== tail) {
    const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;
    logEl.textContent = tail;
    if (atBottom) logEl.scrollTop = logEl.scrollHeight;
  }

  $("run").disabled = s.runner.state === "running";
  lookbackEl.disabled = s.runner.state === "running";

  let applyDisabled = false, applyTitle = "";
  if (s.runner.state === "running")       { applyDisabled = true; applyTitle = "Runner is still running"; }
  else if (s.applier.state === "running") { applyDisabled = true; applyTitle = "Applier is already running"; }
  else if (!s.report.exists)              { applyDisabled = true; applyTitle = "No report yet — run Dream first"; }
  else if (s.report.is_applied)           { applyDisabled = true; applyTitle = "This report was already applied — run Dream again for a fresh one"; }
  else if (!s.report.has_checked)         { applyDisabled = true; applyTitle = "Nothing checked — tick items first"; }
  $("apply").disabled = applyDisabled;
  $("apply").title = applyTitle;

  const r = s.report;
  if (r.exists) {
    $("report-name").textContent = r.path.split("/").pop();
    const d = new Date(r.mtime * 1000);
    const stamp = " · updated " + d.toLocaleString();
    $("report-mtime").textContent = r.is_applied ? (stamp + " · applied") : stamp;
    const link = $("report-link");
    link.href = r.file_url;
    link.style.display = "inline";
    // Re-render only if path changed or external mtime bump we didn't cause.
    if (r.path !== lastReportPath || r.mtime !== lastReportMtime) {
      lastReportPath = r.path;
      lastReportMtime = r.mtime;
      await loadReport();
    }
  } else {
    $("report-name").textContent = "(no report)";
    $("report-mtime").textContent = "";
    $("report-link").style.display = "none";
    $("report-body").textContent = "Run Dream to generate a report.";
    $("report-body").classList.add("muted");
    lastReportPath = null; lastReportMtime = null;
  }

  return s.runner.state === "running" || s.applier.state === "running";
}

const TASK_RE = /^\s*-\s*\[([ xX])\]/;

function findTaskLines(md) {
  const out = [];
  md.split("\n").forEach((line, i) => {
    const m = line.match(TASK_RE);
    if (m) out.push({ line: i, checked: m[1] !== " " });
  });
  return out;
}

async function loadReport() {
  const p = curProject();
  const md = await getText(`/report?project=${encodeURIComponent(p)}`);
  const body = $("report-body");
  if (md == null) {
    body.textContent = "Run Dream to generate a report.";
    body.classList.add("muted");
    return;
  }
  body.classList.remove("muted");
  body.innerHTML = marked.parse(md, { gfm: true, breaks: false });

  // Mark rendered task-list checkboxes with their source line index so a
  // single delegated "change" listener (below) can write them back.
  const taskLines = findTaskLines(md);
  const inputs = body.querySelectorAll('input[type="checkbox"]');
  console.debug(`dream: taskLines=${taskLines.length} inputs=${inputs.length}`);
  inputs.forEach((el, idx) => {
    const meta = taskLines[idx];
    if (!meta) return;
    el.removeAttribute("disabled");
    el.disabled = false;
    el.checked = meta.checked;
    el.dataset.mdLine = String(meta.line);
  });
}

// Delegated change handler — wired once, survives every re-render.
$("report-body").addEventListener("change", async (ev) => {
  const el = ev.target;
  if (!(el instanceof HTMLInputElement) || el.type !== "checkbox") return;
  const lineStr = el.dataset.mdLine;
  if (lineStr === undefined) return;
  const line = parseInt(lineStr, 10);
  const desired = el.checked;
  el.disabled = true;
  const r = await postJSON(
    `/report/toggle?project=${encodeURIComponent(curProject())}`,
    { line, checked: desired }
  );
  el.disabled = false;
  if (!r.ok) {
    el.checked = !desired;
    alert("Failed to save: " + (r.body.error || r.status));
    return;
  }
  // Adopt the server's new mtime so the status poll won't trigger a
  // flicker-rerender on the next tick.
  lastReportMtime = r.body.mtime;
  refreshStatus();
});

$("run").addEventListener("click", async () => {
  $("run").disabled = true;
  const lookback = clampLookback(parseInt(lookbackEl.value, 10));
  lookbackEl.value = String(lookback);
  try { localStorage.setItem(LOOKBACK_STORAGE_KEY, String(lookback)); } catch {}
  const r = await postJSON("/run", { lookback_days: lookback });
  if (!r.ok) alert("Failed to start runner: " + (r.body.error || r.status));
  refreshStatus();
});
$("apply").addEventListener("click", async () => {
  $("apply").disabled = true;
  const p = curProject();
  const r = await postJSON(`/apply?project=${encodeURIComponent(p)}`);
  if (!r.ok) alert("Failed to start applier: " + (r.body.error || r.status));
  refreshStatus();
});
$("reload-report").addEventListener("click", async () => {
  lastReportPath = null; lastReportMtime = null;
  await refreshStatus();
});
if (projectSel) projectSel.addEventListener("change", async () => {
  lastReportPath = null; lastReportMtime = null;
  await refreshStatus();
});

(async () => { await refreshStatus(); })();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""


# ---- Entry point ------------------------------------------------------------


def _find_chromium() -> Optional[str]:
    """Return the first Chromium-based browser binary we can find, or None."""
    macos_candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in macos_candidates:
        if Path(path).exists():
            return path
    # Linux-ish PATH fallbacks.
    from shutil import which
    for name in ("google-chrome", "chromium", "chromium-browser",
                 "microsoft-edge", "brave-browser"):
        found = which(name)
        if found:
            return found
    return None


def _launch_app_window(url: str) -> Optional[subprocess.Popen]:
    """Launch a chromeless Chromium "app window" pointing at url."""
    binary = _find_chromium()
    if not binary:
        return None
    # Dedicated profile dir: without it, `--app` opens a tab in the user's
    # existing Chrome window instead of a proper chromeless app window.
    profile_dir = DREAM_ROOT / "ui-chrome-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        binary,
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--window-size=1020,800",
        "--no-first-run",
        "--no-default-browser-check",
        # Silence the Edge/Chrome auto-updater + crash-reporter noise that
        # otherwise spams the Flask log on every launch.
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-features=Crashpad",
    ]
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_flask_background() -> None:
    """Run Flask in a daemon thread so the main thread can own the window."""
    def serve():
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False,
                threaded=True)
    threading.Thread(target=serve, daemon=True).start()
    # Give Flask a moment to bind before the window loads the URL.
    time.sleep(0.4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dream UI")
    parser.add_argument(
        "--browser", action="store_true",
        help="Open in the default browser instead of a Chrome app window",
    )
    args = parser.parse_args()

    UI_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    url = f"http://{HOST}:{PORT}"
    print(f"Dream UI: {url}", file=sys.stderr)

    if args.browser or _find_chromium() is None:
        if not args.browser:
            print("No Chromium browser found — falling back to default browser.",
                  file=sys.stderr)
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
        return

    _start_flask_background()
    chrome = _launch_app_window(url)
    assert chrome is not None  # _find_chromium returned a hit
    try:
        chrome.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if chrome.poll() is None:
            try:
                chrome.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
