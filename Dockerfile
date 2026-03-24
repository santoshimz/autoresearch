FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md research_program.md ./
COPY autoresearch ./autoresearch
COPY datasets ./datasets
COPY targets ./targets
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

RUN chmod +x ./scripts/railway_entrypoint.sh

CMD ["./scripts/railway_entrypoint.sh"]
