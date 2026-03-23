from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autoresearch.models import CandidateChange, EvalScore, ExperimentRecord
from autoresearch.report import render_report, write_report
from autoresearch.storage import ExperimentLedger


class ReportTests(unittest.TestCase):
    def test_render_report_includes_summary_and_rows(self) -> None:
        records = [
            ExperimentRecord(
                change=CandidateChange(
                    change_id="clarify-example-readme",
                    title="Clarify README example",
                    target_files=("targets/skills-201/README.md",),
                    summary="Makes the composition example easier to follow.",
                ),
                evaluation=EvalScore(
                    passed_gate=True,
                    score=1.0,
                    datasets=("gate.json", "nightly.json",),
                    passed_cases=6,
                    total_cases=6,
                ),
                accepted=True,
                baseline_score=0.5,
            ).as_dict(),
            ExperimentRecord(
                change=CandidateChange(
                    change_id="weaken-security-copy",
                    title="Unsafe wording",
                    target_files=("targets/skills-201/README.md",),
                    summary="Introduces a forbidden credential persistence hint.",
                ),
                evaluation=EvalScore(
                    passed_gate=False,
                    score=0.2,
                    security_regressions=("persisting credentials",),
                    datasets=("gate.json",),
                    passed_cases=2,
                    total_cases=6,
                ),
                accepted=False,
                baseline_score=0.5,
            ).as_dict(),
        ]

        html = render_report(records, "experiments/history.jsonl")

        self.assertIn("Autoresearch Experiment Report", html)
        self.assertIn("clarify-example-readme", html)
        self.assertIn("weaken-security-copy", html)
        self.assertIn("persisting credentials", html)
        self.assertIn("Latest Accepted", html)

    def test_write_report_reads_ledger_and_writes_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            ledger_path = tmp_path / "history.jsonl"
            output_path = tmp_path / "report.html"

            ledger = ExperimentLedger(ledger_path)
            ledger.append(
                ExperimentRecord(
                    change=CandidateChange(
                        change_id="clarify-example-readme",
                        title="Clarify README example",
                        target_files=("targets/skills-201/README.md",),
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
                )
            )

            write_report(ledger_path, output_path)

            html = output_path.read_text(encoding="utf-8")
            self.assertIn("clarify-example-readme", html)
            self.assertIn("Total Runs", html)


if __name__ == "__main__":
    unittest.main()
