#!/usr/bin/env bash
set -euo pipefail

. .venv/bin/activate
python -m autoresearch.report --ledger experiments/history.jsonl --output experiments/report.html
