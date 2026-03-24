from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from urllib import request
from unittest.mock import patch

from autoresearch.models import CandidateChange, EvalScore, ExperimentRecord
from autoresearch.storage import ExperimentLedger
from autoresearch.web import WebSettings, build_history_payload, create_server, decorate_report_html, run_iteration


class WebTests(unittest.TestCase):
    def test_build_history_payload_includes_summary(self) -> None:
        records = [
            ExperimentRecord(
                change=CandidateChange(
                    change_id="clarify-example-readme",
                    title="Clarify README example",
                    target_files=("README.md",),
                    summary="Makes the composition example easier to follow.",
                ),
                evaluation=EvalScore(
                    passed_gate=True,
                    score=1.0,
                    datasets=("gate.json", "nightly.json"),
                    passed_cases=6,
                    total_cases=6,
                ),
                accepted=True,
                baseline_score=0.5,
            ).as_dict()
        ]

        payload = build_history_payload(records, Path("experiments/history.jsonl"), Path("experiments/report.html"))

        self.assertEqual(payload["summary"]["total_runs"], 1)
        self.assertEqual(payload["summary"]["accepted_runs"], 1)
        self.assertEqual(payload["summary"]["latest_accepted_change_id"], "clarify-example-readme")

    def test_web_settings_default_to_railway_friendly_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PORT": "8080",
            },
            clear=True,
        ):
            settings = WebSettings.from_env()

        self.assertEqual(settings.ledger_path, Path("/data/history.jsonl"))
        self.assertEqual(settings.report_path, Path("/data/report.html"))
        self.assertEqual(settings.port, 8080)
        self.assertTrue(settings.enable_run)
        self.assertEqual(settings.run_strategy, "llm")

    def test_web_server_serves_html_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            ledger_path = tmp_path / "history.jsonl"
            report_path = tmp_path / "report.html"
            ledger = ExperimentLedger(ledger_path)
            ledger.append(
                ExperimentRecord(
                    change=CandidateChange(
                        change_id="clarify-example-readme",
                        title="Clarify README example",
                        target_files=("README.md",),
                        summary="Makes the composition example easier to follow.",
                    ),
                    evaluation=EvalScore(
                        passed_gate=True,
                        score=1.0,
                        datasets=("gate.json",),
                        passed_cases=3,
                        total_cases=3,
                    ),
                    accepted=True,
                    baseline_score=0.5,
                )
            )

            settings = WebSettings(
                ledger_path=ledger_path,
                report_path=report_path,
                host="127.0.0.1",
                port=0,
            )
            server = create_server(settings)
            _, port = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            app_html = None
            embed_html = None
            history = None
            try:
                for _ in range(20):
                    try:
                        app_html = request.urlopen(f"http://127.0.0.1:{port}/app").read().decode("utf-8")
                        embed_html = request.urlopen(f"http://127.0.0.1:{port}/report/embed").read().decode("utf-8")
                        history = json.loads(
                            request.urlopen(f"http://127.0.0.1:{port}/api/history").read().decode("utf-8")
                        )
                        break
                    except Exception:
                        time.sleep(0.1)

                self.assertIsNotNone(app_html)
                self.assertIsNotNone(embed_html)
                self.assertIn("Autoresearch workspace", app_html)
                self.assertIn("Run once (library)", app_html)
                self.assertIn("Autoresearch Experiment Report", embed_html)
                self.assertNotIn("Live Controls", embed_html)
                self.assertEqual(history["summary"]["total_runs"], 1)
                self.assertFalse(history["run_controls"]["enabled"])
                self.assertTrue(report_path.exists())
            finally:
                server.shutdown()
                server.server_close()

    def test_root_redirects_to_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = WebSettings(
                ledger_path=tmp_path / "history.jsonl",
                report_path=tmp_path / "report.html",
                host="127.0.0.1",
                port=0,
            )
            server = create_server(settings)
            _, port = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/")
                response = conn.getresponse()
                self.assertEqual(response.status, 302)
                location = response.getheader("Location", "")
                self.assertTrue(location.endswith("/app"))
                conn.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_decorate_report_html_adds_rerun_button(self) -> None:
        html = decorate_report_html(
            "<html><body><main><h1>Report</h1></main></body></html>",
            enable_run=True,
            require_run_auth=True,
            run_strategy="llm",
            last_run_result={
                "ok": True,
                "summary": "completed",
                "strategy": "llm",
                "exit_code": 0,
                "duration_seconds": 1.25,
                "command": ["python", "-m", "autoresearch.cli"],
                "stdout": "winner output",
                "stderr": "warning output",
            },
        )

        self.assertIn("Run Once Now", html)
        self.assertIn("Bearer token", html)
        self.assertIn("Strategy: <code>llm</code>", html)
        self.assertIn("Last run succeeded", html)
        self.assertIn("Last run details", html)
        self.assertIn("winner output", html)
        self.assertIn("warning output", html)

    def test_run_iteration_uses_strategy_and_returns_summary(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(returncode=0, stdout="winner: accepted=True", stderr="")

        result = run_iteration(
            WebSettings(
                ledger_path=Path("experiments/history.jsonl"),
                report_path=Path("experiments/report.html"),
                enable_run=True,
                run_strategy="llm",
            ),
            runner=fake_runner,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["strategy"], "llm")
        self.assertIn("--strategy", captured["command"])
        self.assertIn("llm", captured["command"])
        self.assertEqual(result["summary"], "winner: accepted=True")

    def test_web_server_run_endpoint_returns_runner_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings = WebSettings(
                ledger_path=tmp_path / "history.jsonl",
                report_path=tmp_path / "report.html",
                host="127.0.0.1",
                port=0,
                enable_run=True,
                run_token="secret-token",
                run_strategy="library",
            )
            server = create_server(settings)
            server.run_runner = lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout="clarify-example-readme: accepted=True score=1.00 (6/6 cases)",
                stderr="",
            )
            _, port = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                unauthorized = None
                try:
                    request.urlopen(request.Request(f"http://127.0.0.1:{port}/api/run", method="POST"))
                except Exception as exc:
                    unauthorized = exc
                self.assertIsNotNone(unauthorized)
                response = request.urlopen(
                    request.Request(
                        f"http://127.0.0.1:{port}/api/run",
                        method="POST",
                        headers={"Authorization": "Bearer secret-token"},
                    )
                ).read().decode("utf-8")
                payload = json.loads(response)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["strategy"], "library")
                self.assertIn("accepted=True", payload["summary"])

                captured: dict[str, object] = {}

                def capture_runner(command, **kwargs):
                    captured["command"] = command
                    return SimpleNamespace(returncode=0, stdout="done", stderr="")

                server.run_runner = capture_runner
                response_llm = request.urlopen(
                    request.Request(
                        f"http://127.0.0.1:{port}/api/run",
                        method="POST",
                        headers={
                            "Authorization": "Bearer secret-token",
                            "Content-Type": "application/json",
                        },
                        data=json.dumps({"strategy": "llm"}).encode("utf-8"),
                    )
                ).read().decode("utf-8")
                payload_llm = json.loads(response_llm)
                self.assertTrue(payload_llm["ok"])
                self.assertEqual(payload_llm["strategy"], "llm")
                self.assertIn("--strategy", captured["command"])
                self.assertIn("llm", captured["command"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
