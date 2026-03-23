#!/usr/bin/env bash
set -euo pipefail

. .venv/bin/activate
python -m unittest discover -s tests
