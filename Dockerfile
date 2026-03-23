FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md research_program.md ./
COPY autoresearch ./autoresearch
COPY datasets ./datasets
COPY targets ./targets

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

CMD ["python", "-m", "autoresearch.cli", "--ledger", "experiments/history.jsonl"]
