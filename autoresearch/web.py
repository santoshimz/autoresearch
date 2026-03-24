from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .report import write_report
from .storage import ExperimentLedger


def _running_on_railway() -> bool:
    return any(
        os.environ.get(name, "").strip()
        for name in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
    ) or bool(os.environ.get("PORT", "").strip())


def _default_ledger_path() -> str:
    return "/data/history.jsonl" if _running_on_railway() else "experiments/history.jsonl"


def _default_report_path() -> str:
    return "/data/report.html" if _running_on_railway() else "experiments/report.html"


@dataclass(frozen=True)
class WebSettings:
    ledger_path: Path = Path("experiments/history.jsonl")
    report_path: Path = Path("experiments/report.html")
    host: str = "0.0.0.0"
    port: int = 8000
    enable_run: bool = False
    run_token: str | None = None
    run_strategy: str = "library"
    run_timeout_seconds: int = 600

    @classmethod
    def from_env(cls) -> "WebSettings":
        port_value = os.environ.get("AUTORESEARCH_WEB_PORT", "").strip() or os.environ.get("PORT", "8000")
        return cls(
            ledger_path=Path(os.environ.get("AUTORESEARCH_LEDGER_PATH", _default_ledger_path())).expanduser(),
            report_path=Path(os.environ.get("AUTORESEARCH_REPORT_PATH", _default_report_path())).expanduser(),
            host=os.environ.get("AUTORESEARCH_WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=int(port_value),
            enable_run=_env_flag("AUTORESEARCH_WEB_ENABLE_RUN", default=_running_on_railway()),
            run_token=os.environ.get("AUTORESEARCH_WEB_RUN_TOKEN", "").strip() or None,
            run_strategy=os.environ.get("AUTORESEARCH_WEB_RUN_STRATEGY", "").strip()
            or os.environ.get("AUTORESEARCH_STRATEGY", "llm" if _running_on_railway() else "library").strip()
            or ("llm" if _running_on_railway() else "library"),
            run_timeout_seconds=int(os.environ.get("AUTORESEARCH_WEB_RUN_TIMEOUT_SECONDS", "600")),
        )


def record_strategy_tag(record: dict[str, Any]) -> str:
    meta = record.get("metadata") or {}
    strategy_name = str(meta.get("strategy_name", "")).lower()
    if "llm" in strategy_name:
        return "llm"
    if "library" in strategy_name or "proposal" in strategy_name:
        return "library"
    if meta.get("generator_model") or meta.get("generator_provider"):
        return "llm"
    proposal_kind = str(record.get("change", {}).get("proposal_kind", "")).lower()
    if "llm" in proposal_kind:
        return "llm"
    return "library"


def annotate_records_for_ui(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**record, "strategy_tag": record_strategy_tag(record)} for record in records]


def build_history_payload(records: list[dict[str, Any]], ledger_path: Path, report_path: Path) -> dict[str, Any]:
    accepted_records = [record for record in records if record.get("accepted")]
    gate_passed = [record for record in records if record.get("evaluation", {}).get("passed_gate")]
    best_score = max((float(record.get("evaluation", {}).get("score", 0.0)) for record in records), default=0.0)
    latest_accepted = accepted_records[-1] if accepted_records else None
    library_runs = sum(1 for r in records if record_strategy_tag(r) == "library")
    llm_runs = sum(1 for r in records if record_strategy_tag(r) == "llm")
    return {
        "ledger_path": str(ledger_path),
        "report_path": str(report_path),
        "summary": {
            "total_runs": len(records),
            "accepted_runs": len(accepted_records),
            "gate_passes": len(gate_passed),
            "best_score": best_score,
            "library_runs": library_runs,
            "llm_runs": llm_runs,
            "latest_accepted_change_id": (
                latest_accepted.get("change", {}).get("change_id") if latest_accepted is not None else None
            ),
        },
        "records": annotate_records_for_ui(records),
    }


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_report_html(ledger_path: Path, report_path: Path) -> str:
    write_report(ledger_path, report_path)
    return report_path.read_text(encoding="utf-8")


def decorate_report_html(
    report_html: str,
    *,
    enable_run: bool,
    require_run_auth: bool,
    run_strategy: str,
    last_run_result: dict[str, Any] | None,
) -> str:
    """Legacy helper kept for tests; production UI uses /app + /report/embed instead."""
    status_text = "Ready"
    details_html = (
        '<div style="margin-top:10px;color:#64748b;">No run has been triggered from this web session yet.</div>'
    )
    if last_run_result is not None:
        if last_run_result.get("ok"):
            status_text = f"Last run succeeded: {last_run_result.get('summary', 'completed')}"
        else:
            status_text = f"Last run failed: {last_run_result.get('summary', 'error')}"
        detail_rows = [
            f"<div><strong>Summary:</strong> {html.escape(str(last_run_result.get('summary', '-')))}</div>",
            f"<div><strong>Strategy:</strong> <code>{html.escape(str(last_run_result.get('strategy', '-')))}</code></div>",
        ]
        if "exit_code" in last_run_result:
            detail_rows.append(
                f"<div><strong>Exit code:</strong> <code>{html.escape(str(last_run_result.get('exit_code')))}</code></div>"
            )
        if "duration_seconds" in last_run_result:
            detail_rows.append(
                f"<div><strong>Duration:</strong> <code>{html.escape(str(last_run_result.get('duration_seconds')))}s</code></div>"
            )
        if last_run_result.get("command"):
            command = " ".join(str(part) for part in last_run_result["command"])
            detail_rows.append(f"<div><strong>Command:</strong> <code>{html.escape(command)}</code></div>")
        stdout = str(last_run_result.get("stdout", "")).strip()
        stderr = str(last_run_result.get("stderr", "")).strip()
        stdout_html = (
            f"<div><strong>Stdout</strong><pre style=\"margin:6px 0 0;padding:10px;border-radius:10px;background:#f8fafc;border:1px solid #e2e8f0;white-space:pre-wrap;\">{html.escape(stdout)}</pre></div>"
            if stdout
            else ""
        )
        stderr_html = (
            f"<div><strong>Stderr</strong><pre style=\"margin:6px 0 0;padding:10px;border-radius:10px;background:#fff7ed;border:1px solid #fed7aa;white-space:pre-wrap;\">{html.escape(stderr)}</pre></div>"
            if stderr
            else ""
        )
        details_html = (
            "<details style=\"margin-top:12px;\">"
            "<summary style=\"cursor:pointer;font-weight:600;\">Last run details</summary>"
            f"<div style=\"display:grid;gap:8px;margin-top:10px;color:#334155;\">{''.join(detail_rows)}{stdout_html}{stderr_html}</div>"
            "</details>"
        )
    button_html = (
        '<button id="rerun-button" type="button">Run Once Now</button>'
        if enable_run
        else '<button id="rerun-button" type="button" disabled>Run disabled</button>'
    )
    token_input_html = (
        '<input id="rerun-token" type="password" placeholder="Bearer token" '
        'style="min-width:220px;padding:8px 10px;border:1px solid #cbd5e1;border-radius:10px;" />'
        if enable_run and require_run_auth
        else ""
    )
    auth_note = "Bearer token required" if require_run_auth else "No auth configured"
    controls = f"""
    <section style="margin-bottom:16px;padding:16px;border:1px solid #dbe3ee;border-radius:14px;background:#ffffff;box-shadow:0 8px 30px rgba(15, 23, 42, 0.04);">
      <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;">
        <div>
          <strong>Live Controls</strong>
          <div style="margin-top:6px;color:#475569;">Strategy: <code>{html.escape(run_strategy)}</code> | Auth: {html.escape(auth_note)} | Status: <span id="run-status">{html.escape(status_text)}</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:center;">
          {token_input_html}
          {button_html}
        </div>
      </div>
      {details_html}
    </section>
    <script>
    (() => {{
      const button = document.getElementById("rerun-button");
      const status = document.getElementById("run-status");
      const tokenInput = document.getElementById("rerun-token");
      if (!button || button.disabled) return;
      if (tokenInput) {{
        tokenInput.value = window.sessionStorage.getItem("autoresearch-run-token") || "";
      }}
      button.addEventListener("click", async () => {{
        button.disabled = true;
        status.textContent = "Running...";
        try {{
          const headers = {{}};
          if (tokenInput) {{
            const token = tokenInput.value.trim();
            if (!token) {{
              throw new Error("Bearer token required");
            }}
            window.sessionStorage.setItem("autoresearch-run-token", token);
            headers["Authorization"] = `Bearer ${{token}}`;
          }}
          const response = await fetch("/api/run", {{ method: "POST", headers }});
          const payload = await response.json();
          if (!response.ok || !payload.ok) {{
            throw new Error(payload.summary || payload.error || "Run failed");
          }}
          status.textContent = payload.summary || "Run completed";
          window.location.reload();
        }} catch (error) {{
          status.textContent = error.message;
          button.disabled = false;
        }}
      }});
    }})();
    </script>
    """
    return report_html.replace("<main>", f"<main>{controls}", 1)


APP_SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>autoresearch workspace</title>
  <style>
    :root { color-scheme: light; --border: #dbe3ee; --muted: #64748b; --text: #0f172a; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #f8fafc; color: var(--text); }
    main { max-width: 1280px; margin: 0 auto; padding: 24px 16px 40px; }
    .hero { padding: 20px 22px; border-radius: 16px; background: linear-gradient(135deg, #0f172a, #1e293b); color: #f8fafc; margin-bottom: 20px; }
    .hero h1 { margin: 0 0 8px; font-size: 1.5rem; }
    .hero p { margin: 0; color: rgba(248,250,252,0.85); line-height: 1.5; font-size: 0.95rem; }
    .layout { display: grid; grid-template-columns: minmax(280px, 340px) 1fr; gap: 16px; align-items: start; }
    @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
    .panel { background: #fff; border: 1px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: 0 8px 24px rgba(15,23,42,0.04); }
    .panel h2 { margin: 0 0 8px; font-size: 1rem; }
    .panel p.hint { margin: 0 0 12px; font-size: 0.85rem; color: var(--muted); line-height: 1.5; }
    label { display: block; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin-bottom: 6px; }
    input[type=password], select { width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 10px; font: inherit; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    button { padding: 10px 14px; border-radius: 10px; border: 1px solid #cbd5e1; background: #fff; font: inherit; cursor: pointer; }
    button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
    button.secondary { background: #f1f5f9; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
    .stat { padding: 10px; border-radius: 10px; background: #f8fafc; border: 1px solid var(--border); font-size: 0.85rem; }
    .stat strong { display: block; font-size: 1.1rem; color: var(--text); }
    #runs { max-height: 280px; overflow-y: auto; margin-top: 10px; }
    .run-item { padding: 10px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; cursor: pointer; font-size: 0.85rem; }
    .run-item:hover { background: #f8fafc; }
    .run-item.active { border-color: #2563eb; background: #eff6ff; }
    .chip { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
    .chip.library { background: #e0f2fe; color: #0369a1; }
    .chip.llm { background: #ede9fe; color: #5b21b6; }
    .viewer-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
    .viewer-frame { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: #fff; min-height: 70vh; }
    iframe { width: 100%; min-height: 70vh; border: 0; display: block; }
    #status { margin-top: 8px; padding: 8px 10px; border-radius: 8px; font-size: 0.85rem; background: #f1f5f9; color: var(--text); }
    #status[data-tone=success] { background: #dcfce7; color: #166534; }
    #status[data-tone=error] { background: #fee2e2; color: #991b1b; }
    a.json-link { font-size: 0.85rem; color: #2563eb; }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>Autoresearch workspace</h1>
      <p>Save your run token if the server requires it, choose library or LLM runs, filter ledger rows, and view the HTML report separately in the viewer—similar to evals-101.</p>
    </section>
    <div class="layout">
      <aside>
        <section class="panel">
          <h2>Access</h2>
          <p class="hint">When <code>AUTORESEARCH_WEB_RUN_TOKEN</code> is set on the server, paste the same value here. Stored only in this browser session.</p>
          <label for="token">Bearer token</label>
          <input id="token" type="password" placeholder="Run API token" autocomplete="off">
          <div class="row">
            <button type="button" class="secondary" id="save-token">Save token</button>
            <button type="button" class="secondary" id="refresh" data-busy-label="Refreshing...">Refresh</button>
          </div>
        </section>
        <section class="panel" style="margin-top:14px;">
          <h2>Run actions</h2>
          <p class="hint">Each button runs one iteration with the chosen strategy. Default from env applies only if you use the API without a body.</p>
          <div class="row">
            <button type="button" class="primary" id="run-library" data-busy-label="Running library...">Run once (library)</button>
            <button type="button" class="primary" id="run-llm" data-busy-label="Running LLM...">Run once (LLM)</button>
          </div>
        </section>
        <section class="panel" style="margin-top:14px;">
          <h2>Ledger filter</h2>
          <label for="filter">Show rows</label>
          <select id="filter">
            <option value="all">All</option>
            <option value="library">Library only</option>
            <option value="llm">LLM only</option>
          </select>
          <div class="stats">
            <div class="stat"><span>Total rows</span><strong id="stat-total">0</strong></div>
            <div class="stat"><span>Library / LLM</span><strong id="stat-split">0 / 0</strong></div>
          </div>
        </section>
        <section class="panel" style="margin-top:14px;">
          <h2>Recent ledger rows</h2>
          <p class="hint">Newest first. Use <strong>Open raw JSON</strong> for full row payloads; the report panel loads HTML only after a run or Reload.</p>
          <div id="status" data-tone="neutral">Ready.</div>
          <div id="runs"></div>
          <p style="margin-top:12px;"><a class="json-link" href="/api/history" target="_blank" rel="noopener">Open raw JSON (/api/history)</a></p>
        </section>
      </aside>
      <section class="panel">
        <div class="viewer-header">
          <div>
            <h2 style="margin:0 0 6px;">Report viewer</h2>
            <p style="margin:0;font-size:0.9rem;color:var(--muted);">Starts empty. The HTML report loads here after a run succeeds, or when you click Reload report.</p>
          </div>
          <button type="button" class="secondary" id="reload-report">Reload report</button>
        </div>
        <div class="viewer-frame">
          <iframe id="viewer" title="Autoresearch experiment report" src="about:blank"></iframe>
        </div>
      </section>
    </div>
  </main>
  <script>
  (function() {
    const TOKEN_KEY = "autoresearchRunToken";
    const tokenInput = document.getElementById("token");
    const status = document.getElementById("status");
    const runsNode = document.getElementById("runs");
    const viewer = document.getElementById("viewer");
    const filterEl = document.getElementById("filter");
    const statTotal = document.getElementById("stat-total");
    const statSplit = document.getElementById("stat-split");

    const VIEWER_PLACEHOLDER = "<!DOCTYPE html><html lang=\\"en\\"><head><meta charset=\\"utf-8\\"><style>" +
      "body{margin:0;min-height:70vh;display:grid;place-items:center;font-family:Inter,system-ui,sans-serif;" +
      "padding:32px;background:#f8fafc;color:#475569;text-align:center;line-height:1.6}" +
      "strong{color:#0f172a;display:block;margin-bottom:10px;font-size:1.05rem}</style></head><body><div>" +
      "<strong>No report loaded yet</strong>" +
      "<p>Run once (library) or Run once (LLM). When the run finishes successfully, the experiment report opens here.</p>" +
      "<p style=\\"font-size:0.9rem;margin-top:14px\\">Or click <strong>Reload report</strong> to load the latest HTML from the ledger without starting a new run.</p>" +
      "</div></body></html>";

    viewer.srcdoc = VIEWER_PLACEHOLDER;

    tokenInput.value = sessionStorage.getItem(TOKEN_KEY) || "";

    function setStatus(msg, tone) {
      status.textContent = msg;
      status.dataset.tone = tone || "neutral";
    }

    function getToken() {
      return tokenInput.value.trim();
    }

    function authHeaders() {
      const h = new Headers();
      const t = getToken();
      if (t) h.set("Authorization", "Bearer " + t);
      return h;
    }

    document.getElementById("save-token").addEventListener("click", function() {
      sessionStorage.setItem(TOKEN_KEY, getToken());
      setStatus("Token saved for this browser session.", "success");
    });

    function bustReportUrl() {
      return "/report/embed?t=" + Date.now();
    }

    function reloadReport() {
      viewer.removeAttribute("srcdoc");
      viewer.src = bustReportUrl();
    }

    document.getElementById("reload-report").addEventListener("click", reloadReport);

    function escapeHtml(s) {
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    }

    let latestRecords = [];

    function renderRuns() {
      const f = filterEl.value;
      const filtered = latestRecords.filter(function(r) {
        const tag = r.strategy_tag || "library";
        if (f === "all") return true;
        return tag === f;
      });
      if (!filtered.length) {
        runsNode.innerHTML = "<p class=\\"hint\\" style=\\"margin:0\\">No rows match this filter.</p>";
        return;
      }
      runsNode.innerHTML = filtered.map(function(r, i) {
        const ch = r.change || {};
        const ev = r.evaluation || {};
        const tag = r.strategy_tag || "library";
        const id = escapeHtml(ch.change_id || "-");
        const score = ev.score != null ? Number(ev.score).toFixed(2) : "-";
        const acc = r.accepted ? "yes" : "no";
        return "<div class=\\"run-item\\" data-idx=\\"" + i + "\\">" +
          "<span class=\\"chip " + escapeHtml(tag) + "\\">" + escapeHtml(tag) + "</span> " +
          "<code>" + id + "</code> · score " + score + " · accepted " + acc + "</div>";
      }).join("");
    }

    async function loadHistory() {
      setStatus("Loading…", "neutral");
      try {
        const res = await fetch("/api/history", { headers: authHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed to load history");
        latestRecords = data.records || [];
        statTotal.textContent = String(latestRecords.length);
        const lib = (data.summary && data.summary.library_runs) != null ? data.summary.library_runs : 0;
        const llm = (data.summary && data.summary.llm_runs) != null ? data.summary.llm_runs : 0;
        statSplit.textContent = lib + " / " + llm;
        renderRuns();
        setStatus("Loaded " + latestRecords.length + " ledger rows.", "success");
      } catch (e) {
        setStatus(e.message || String(e), "error");
        runsNode.innerHTML = "";
      }
    }

    filterEl.addEventListener("change", renderRuns);

    document.getElementById("refresh").addEventListener("click", loadHistory);

    function setBusy(btn, busy) {
      if (!btn) return;
      if (busy) {
        btn.dataset._label = btn.textContent;
        btn.textContent = btn.dataset.busyLabel || btn.textContent;
        btn.disabled = true;
      } else {
        btn.textContent = btn.dataset._label || btn.textContent;
        btn.disabled = false;
      }
    }

    async function runStrategy(strategy) {
      const btn = strategy === "llm" ? document.getElementById("run-llm") : document.getElementById("run-library");
      setBusy(btn, true);
      setStatus("Running " + strategy + "…", "neutral");
      try {
        const headers = authHeaders();
        headers.set("Content-Type", "application/json");
        const res = await fetch("/api/run", {
          method: "POST",
          headers: headers,
          body: JSON.stringify({ strategy: strategy })
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload.summary || payload.error || "Run failed");
        }
        setStatus(payload.summary || "Run completed.", "success");
        await loadHistory();
        reloadReport();
      } catch (e) {
        setStatus(e.message || String(e), "error");
      } finally {
        setBusy(btn, false);
      }
    }

    document.getElementById("run-library").addEventListener("click", function() { runStrategy("library"); });
    document.getElementById("run-llm").addEventListener("click", function() { runStrategy("llm"); });

    loadHistory();
  })();
  </script>
</body>
</html>
"""


def run_iteration(
    settings: WebSettings,
    *,
    strategy: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    effective = strategy if strategy in ("library", "llm") else settings.run_strategy
    if effective not in ("library", "llm"):
        effective = "library"
    command = [sys.executable, "-m", "autoresearch.cli", "--ledger", str(settings.ledger_path)]
    if effective != "library":
        command.extend(["--strategy", effective])
    started_at = time.time()
    completed = runner(
        command,
        capture_output=True,
        text=True,
        timeout=settings.run_timeout_seconds,
        check=False,
        env=os.environ.copy(),
    )
    duration_seconds = round(time.time() - started_at, 3)
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    ok = completed.returncode == 0
    summary = stdout.splitlines()[-1] if stdout else ("completed" if ok else "run failed")
    result: dict[str, Any] = {
        "ok": ok,
        "strategy": effective,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": duration_seconds,
        "summary": summary,
    }
    if strategy is not None:
        result["requested_strategy"] = strategy
    return result


def _path_only(raw_path: str) -> str:
    return raw_path.split("?", 1)[0].rstrip("/") or "/"


class AutoresearchRequestHandler(BaseHTTPRequestHandler):
    server_version = "autoresearch-web/0.2"

    def __init__(self, *args, settings: WebSettings, **kwargs):
        self.settings = settings
        super().__init__(*args, **kwargs)

    def _read_records(self) -> list[dict[str, Any]]:
        return ExperimentLedger(self.settings.ledger_path).read_records()

    def _server_last_run_result(self) -> dict[str, Any] | None:
        return getattr(self.server, "last_run_result", None)

    def _run_enabled(self) -> bool:
        return self.settings.enable_run and bool(self.settings.run_token)

    def _run_is_authorized(self) -> bool:
        token = self.settings.run_token
        if not token:
            return False
        authorization = self.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        return authorization == expected

    def _send_html(self, html_out: str) -> None:
        body = html_out.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = _path_only(self.path)

        if path == "/":
            host = self.headers.get("Host", "localhost")
            scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
            self._send_redirect(f"{scheme}://{host}/app")
            return

        if path in ("/report", "/report.html"):
            host = self.headers.get("Host", "localhost")
            scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
            self._send_redirect(f"{scheme}://{host}/report/embed")
            return

        if path == "/app":
            self._send_html(APP_SHELL_HTML)
            return

        if path == "/report/embed":
            self._send_html(build_report_html(self.settings.ledger_path, self.settings.report_path))
            return

        if path == "/api/history":
            records = self._read_records()
            payload = build_history_payload(records, self.settings.ledger_path, self.settings.report_path)
            payload["run_controls"] = {
                "enabled": self._run_enabled(),
                "requires_bearer_auth": bool(self.settings.run_token),
                "default_strategy": self.settings.run_strategy,
                "last_run_result": self._server_last_run_result(),
            }
            self._send_json(payload)
            return

        if path == "/health":
            self._send_json({"ok": True, "ledger_path": str(self.settings.ledger_path)})
            return

        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = _path_only(self.path)
        if path != "/api/run":
            self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        if not self.settings.enable_run:
            self._send_json({"ok": False, "error": "run_disabled"}, status=HTTPStatus.FORBIDDEN)
            return
        if not self.settings.run_token:
            self._send_json({"ok": False, "error": "run_token_missing"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if not self._run_is_authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Bearer realm="autoresearch"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"ok": False, "error": "unauthorized"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        run_lock = getattr(self.server, "run_lock")
        if not run_lock.acquire(blocking=False):
            self._send_json({"ok": False, "error": "run_in_progress"}, status=HTTPStatus.CONFLICT)
            return

        try:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                length = 0
            raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
            strategy_override: str | None = None
            if raw_body.strip():
                try:
                    data = json.loads(raw_body)
                except json.JSONDecodeError:
                    self._send_json({"ok": False, "error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not isinstance(data, dict):
                    self._send_json({"ok": False, "error": "invalid_body"}, status=HTTPStatus.BAD_REQUEST)
                    return
                s = data.get("strategy")
                if s is not None:
                    if s not in ("library", "llm"):
                        self._send_json({"ok": False, "error": "invalid_strategy"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    strategy_override = s
            effective_strategy = strategy_override if strategy_override is not None else self.settings.run_strategy
            try:
                result = run_iteration(
                    self.settings,
                    strategy=effective_strategy,
                    runner=getattr(self.server, "run_runner"),
                )
                setattr(self.server, "last_run_result", result)
                status = HTTPStatus.OK if result.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR
                self._send_json(result, status=status)
            except subprocess.TimeoutExpired:
                result = {
                    "ok": False,
                    "strategy": self.settings.run_strategy,
                    "summary": f"Run timed out after {self.settings.run_timeout_seconds}s",
                }
                setattr(self.server, "last_run_result", result)
                self._send_json(result, status=HTTPStatus.GATEWAY_TIMEOUT)
        finally:
            run_lock.release()

    def log_message(self, format: str, *args) -> None:
        return


def serve(settings: WebSettings) -> None:
    handler = partial(AutoresearchRequestHandler, settings=settings)
    server = create_server(settings)
    host, port = server.server_address
    print(
        f"serving autoresearch on http://{host}:{port}/app "
        f"(ledger={settings.ledger_path})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def create_server(settings: WebSettings) -> ThreadingHTTPServer:
    handler = partial(AutoresearchRequestHandler, settings=settings)
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    server.run_lock = threading.Lock()
    server.last_run_result = None
    server.run_runner = subprocess.run
    return server


def main() -> None:
    defaults = WebSettings.from_env()
    parser = argparse.ArgumentParser(description="Serve the autoresearch report over HTTP.")
    parser.add_argument("--ledger", default=str(defaults.ledger_path))
    parser.add_argument("--output", default=str(defaults.report_path))
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    args = parser.parse_args()
    serve(
        WebSettings(
            ledger_path=Path(args.ledger),
            report_path=Path(args.output),
            host=args.host,
            port=args.port,
            enable_run=defaults.enable_run,
            run_token=defaults.run_token,
            run_strategy=defaults.run_strategy,
            run_timeout_seconds=defaults.run_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
