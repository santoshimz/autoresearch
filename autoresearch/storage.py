from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ExperimentRecord


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: ExperimentRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")

    def read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def current_baseline(self, default: float) -> float:
        best = default
        for record in self.read_records():
            if record.get("accepted"):
                evaluation = record.get("evaluation", {})
                score = float(evaluation.get("score", default))
                if score > best:
                    best = score
        return best
