from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from .storage import ExperimentLedger


def _as_bool_label(value: bool) -> str:
    return "yes" if value else "no"


def _format_float(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}"


def _join_items(items: list[str] | tuple[str, ...]) -> str:
    if not items:
        return "-"
    return ", ".join(str(item) for item in items)


def _build_score_chart(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty">No experiment rows yet. Run `./scripts/run_local.sh` first.</div>'

    width = 720
    height = 220
    padding = 28
    max_score = max(
        1.0,
        max(float(record.get("evaluation", {}).get("score", 0.0)) for record in records),
    )
    usable_width = width - padding * 2
    usable_height = height - padding * 2

    points: list[str] = []
    accepted_points: list[str] = []
    for index, record in enumerate(records):
        evaluation = record.get("evaluation", {})
        score = float(evaluation.get("score", 0.0))
        x = padding if len(records) == 1 else padding + usable_width * index / (len(records) - 1)
        y = padding + usable_height * (1.0 - (score / max_score))
        points.append(f"{x:.1f},{y:.1f}")
        if record.get("accepted"):
            accepted_points.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#0f766e" stroke="#ffffff" stroke-width="2" />'
            )

    guide_lines = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = padding + usable_height * (1.0 - fraction)
        label = max_score * fraction
        guide_lines.append(
            f'<line x1="{padding}" y1="{y:.1f}" x2="{width - padding}" y2="{y:.1f}" class="grid" />'
        )
        guide_lines.append(
            f'<text x="6" y="{y + 4:.1f}" class="axis-label">{html.escape(_format_float(label))}</text>'
        )

    return f"""
    <svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="Experiment score over time">
      {''.join(guide_lines)}
      <polyline fill="none" stroke="#2563eb" stroke-width="3" points="{' '.join(points)}" />
      {''.join(accepted_points)}
      <text x="{width - 180}" y="20" class="axis-label">Accepted runs are highlighted</text>
    </svg>
    """


def render_report(records: list[dict[str, Any]], ledger_path: str) -> str:
    accepted_records = [record for record in records if record.get("accepted")]
    gate_passed = [record for record in records if record.get("evaluation", {}).get("passed_gate")]
    best_score = max(
        (float(record.get("evaluation", {}).get("score", 0.0)) for record in records),
        default=0.0,
    )
    latest_accepted = accepted_records[-1] if accepted_records else None

    rows = []
    for index, record in enumerate(reversed(records), start=1):
        evaluation = record.get("evaluation", {})
        change = record.get("change", {})
        rows.append(
            f"""
            <tr>
              <td>{len(records) - index + 1}</td>
              <td><code>{html.escape(str(change.get("change_id", "-")))}</code></td>
              <td>{html.escape(str(change.get("title", "-")))}</td>
              <td>{html.escape(_format_float(evaluation.get("score")))}</td>
              <td>{html.escape(_as_bool_label(bool(record.get("accepted"))))}</td>
              <td>{html.escape(_as_bool_label(bool(evaluation.get("passed_gate"))))}</td>
              <td>{html.escape(f"{evaluation.get('passed_cases', 0)}/{evaluation.get('total_cases', 0)}")}</td>
              <td>{html.escape(_join_items(evaluation.get("datasets", [])))}</td>
              <td>{html.escape(_join_items(evaluation.get("security_regressions", [])))}</td>
              <td>{html.escape(str(change.get("summary", "-")))}</td>
            </tr>
            """
        )

    latest_accepted_text = "-"
    if latest_accepted is not None:
        latest_change = latest_accepted.get("change", {})
        latest_eval = latest_accepted.get("evaluation", {})
        latest_accepted_text = (
            f"{latest_change.get('change_id', '-')} "
            f"({_format_float(latest_eval.get('score'))})"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Autoresearch Experiment Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8fafc;
      --panel: #ffffff;
      --border: #dbe3ee;
      --text: #0f172a;
      --muted: #475569;
      --blue: #2563eb;
      --green: #0f766e;
      --amber: #b45309;
      --red: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    main {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .subtitle {{ margin-top: 8px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 8px 30px rgba(15, 23, 42, 0.04);
    }}
    .metric {{
      font-size: 30px;
      font-weight: 700;
      margin-top: 6px;
    }}
    .metric-label {{
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .chart {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .grid {{
      stroke: #e2e8f0;
      stroke-width: 1;
    }}
    .axis-label {{
      fill: #64748b;
      font-size: 11px;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
    }}
    .empty {{
      border: 1px dashed var(--border);
      border-radius: 12px;
      padding: 24px;
      color: var(--muted);
      background: #fbfdff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 12px 10px;
      border-top: 1px solid var(--border);
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }}
    .legend {{
      display: flex;
      gap: 16px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-right: 6px;
    }}
    .blue {{ background: var(--blue); }}
    .green {{ background: var(--green); }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      main {{ padding: 20px 14px 32px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Autoresearch Experiment Report</h1>
    <p class="subtitle">Static report generated from <code>{html.escape(ledger_path)}</code>.</p>

    <section class="cards">
      <div class="card">
        <div class="metric-label">Total Runs</div>
        <div class="metric">{len(records)}</div>
      </div>
      <div class="card">
        <div class="metric-label">Accepted Runs</div>
        <div class="metric">{len(accepted_records)}</div>
      </div>
      <div class="card">
        <div class="metric-label">Gate Passes</div>
        <div class="metric">{len(gate_passed)}</div>
      </div>
      <div class="card">
        <div class="metric-label">Best Score</div>
        <div class="metric">{_format_float(best_score)}</div>
      </div>
      <div class="card">
        <div class="metric-label">Latest Accepted</div>
        <div class="metric" style="font-size: 20px;">{html.escape(latest_accepted_text)}</div>
      </div>
    </section>

    <section class="layout">
      <div class="panel">
        <h2>Score Trend</h2>
        <p>Points are ordered by ledger sequence. Accepted runs are highlighted.</p>
        {_build_score_chart(records)}
        <div class="legend">
          <span><span class="dot blue"></span>score</span>
          <span><span class="dot green"></span>accepted</span>
        </div>
      </div>
      <div class="panel">
        <h2>How to regenerate</h2>
        <p>Run the report after local experiments to get a static artifact you can open in a browser or attach to a handoff.</p>
        <pre><code>./scripts/render_report.sh
open experiments/report.html</code></pre>
      </div>
    </section>

    <section class="panel">
      <h2>Experiment History</h2>
      <p>Newest rows appear first. Security regressions are shown inline so unsafe candidates stay easy to spot.</p>
      <div style="overflow-x: auto; margin-top: 14px;">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Change ID</th>
              <th>Title</th>
              <th>Score</th>
              <th>Accepted</th>
              <th>Gate Passed</th>
              <th>Cases</th>
              <th>Datasets</th>
              <th>Security Regressions</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows) if rows else '<tr><td colspan="10">No experiments recorded yet.</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def write_report(ledger_path: Path, output_path: Path) -> None:
    records = ExperimentLedger(ledger_path).read_records()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(records, str(ledger_path)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a static HTML report from the experiment ledger.")
    parser.add_argument("--ledger", default="experiments/history.jsonl", help="Path to the experiment ledger JSONL file.")
    parser.add_argument("--output", default="experiments/report.html", help="Path to write the static HTML report.")
    args = parser.parse_args()

    write_report(Path(args.ledger), Path(args.output))
    print(f"wrote report to {args.output}")


if __name__ == "__main__":
    main()
