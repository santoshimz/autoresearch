#!/usr/bin/env bash
set -euo pipefail

. .venv/bin/activate
python -m autoresearch.web --ledger experiments/history.jsonl --output experiments/report.html
