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

from .report import render_report, write_report
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


def build_history_payload(records: list[dict[str, Any]], ledger_path: Path, report_path: Path) -> dict[str, Any]:
    accepted_records = [record for record in records if record.get("accepted")]
    gate_passed = [record for record in records if record.get("evaluation", {}).get("passed_gate")]
    best_score = max((float(record.get("evaluation", {}).get("score", 0.0)) for record in records), default=0.0)
    latest_accepted = accepted_records[-1] if accepted_records else None
    return {
        "ledger_path": str(ledger_path),
        "report_path": str(report_path),
        "summary": {
            "total_runs": len(records),
            "accepted_runs": len(accepted_records),
            "gate_passes": len(gate_passed),
            "best_score": best_score,
            "latest_accepted_change_id": (
                latest_accepted.get("change", {}).get("change_id") if latest_accepted is not None else None
            ),
        },
        "records": records,
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


def run_iteration(
    settings: WebSettings,
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    command = [sys.executable, "-m", "autoresearch.cli", "--ledger", str(settings.ledger_path)]
    if settings.run_strategy != "library":
        command.extend(["--strategy", settings.run_strategy])
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
    return {
        "ok": ok,
        "strategy": settings.run_strategy,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": duration_seconds,
        "summary": summary,
    }


class AutoresearchRequestHandler(BaseHTTPRequestHandler):
    server_version = "autoresearch-web/0.1"

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

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/report", "/report.html"):
            self._send_html(
                decorate_report_html(
                    build_report_html(self.settings.ledger_path, self.settings.report_path),
                    enable_run=self._run_enabled(),
                    require_run_auth=bool(self.settings.run_token),
                    run_strategy=self.settings.run_strategy,
                    last_run_result=self._server_last_run_result(),
                )
            )
            return

        if self.path == "/api/history":
            records = self._read_records()
            payload = build_history_payload(records, self.settings.ledger_path, self.settings.report_path)
            payload["run_controls"] = {
                "enabled": self._run_enabled(),
                "requires_bearer_auth": bool(self.settings.run_token),
                "strategy": self.settings.run_strategy,
                "last_run_result": self._server_last_run_result(),
            }
            self._send_json(payload)
            return

        if self.path == "/health":
            self._send_json({"ok": True, "ledger_path": str(self.settings.ledger_path)})
            return

        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/run":
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
            result = run_iteration(self.settings, runner=getattr(self.server, "run_runner"))
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
        f"serving autoresearch report on http://{host}:{port} "
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
