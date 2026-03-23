FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md research_program.md ./
COPY autoresearch ./autoresearch

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

CMD ["python", "-m", "autoresearch.cli", "--baseline-score", "0.7", "--ledger", "experiments/history.jsonl"]
