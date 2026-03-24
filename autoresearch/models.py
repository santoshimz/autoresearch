from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FilePatch:
    path: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class CandidateChange:
    change_id: str
    title: str
    target_files: tuple[str, ...]
    summary: str
    proposal_kind: str = "documentation"
    patches: tuple[FilePatch, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalScore:
    passed_gate: bool
    score: float
    security_regressions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    passed_cases: int = 0
    total_cases: int = 0


@dataclass(frozen=True)
class ExperimentRecord:
    change: CandidateChange
    evaluation: EvalScore
    accepted: bool
    baseline_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
