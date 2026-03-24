#!/usr/bin/env sh
set -eu

IS_RAILWAY=0
if [ -n "${RAILWAY_ENVIRONMENT:-}" ] || [ -n "${RAILWAY_PROJECT_ID:-}" ] || [ -n "${RAILWAY_SERVICE_ID:-}" ] || [ -n "${PORT:-}" ]; then
  IS_RAILWAY=1
fi

DEFAULT_LEDGER_PATH="experiments/history.jsonl"
DEFAULT_REPORT_PATH="experiments/report.html"
DEFAULT_SERVICE_MODE="worker"
DEFAULT_ON_DEMAND="0"
DEFAULT_RUN_INTERVAL_SECONDS="0"

if [ "$IS_RAILWAY" = "1" ]; then
  DEFAULT_LEDGER_PATH="/data/history.jsonl"
  DEFAULT_REPORT_PATH="/data/report.html"
  DEFAULT_SERVICE_MODE="web"
fi

LEDGER_PATH="${AUTORESEARCH_LEDGER_PATH:-$DEFAULT_LEDGER_PATH}"
REPORT_PATH="${AUTORESEARCH_REPORT_PATH:-$DEFAULT_REPORT_PATH}"
RUN_INTERVAL_SECONDS="${AUTORESEARCH_RUN_INTERVAL_SECONDS:-$DEFAULT_RUN_INTERVAL_SECONDS}"
ON_DEMAND="${AUTORESEARCH_ON_DEMAND:-$DEFAULT_ON_DEMAND}"
SERVICE_MODE="${AUTORESEARCH_SERVICE_MODE:-$DEFAULT_SERVICE_MODE}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

run_once() {
  "$PYTHON_BIN" -m autoresearch.cli --ledger "$LEDGER_PATH"
}

serve_web() {
  autoresearch-web --ledger "$LEDGER_PATH" --output "$REPORT_PATH"
}

if [ "$SERVICE_MODE" = "web" ]; then
  echo "starting autoresearch web service with ledger=$LEDGER_PATH report=$REPORT_PATH"
  serve_web
  exit 0
fi

idle_forever() {
  echo "worker is idle; trigger a rerun with a manual Railway redeploy"
  while true; do
    sleep 3600
  done
}

if [ "$ON_DEMAND" = "1" ]; then
  echo "starting autoresearch worker in on-demand mode with ledger=$LEDGER_PATH"
  run_once
  idle_forever
fi

if [ "$RUN_INTERVAL_SECONDS" -le 0 ]; then
  run_once
  exit 0
fi

echo "starting autoresearch worker with ledger=$LEDGER_PATH interval=${RUN_INTERVAL_SECONDS}s"

while true; do
  run_once
  echo "sleeping ${RUN_INTERVAL_SECONDS}s before next run"
  sleep "$RUN_INTERVAL_SECONDS"
done
