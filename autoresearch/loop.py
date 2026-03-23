from __future__ import annotations

import argparse
from pathlib import Path
from typing import Protocol

from .config import SKILLS_201_PROFILE, approved_paths
from .evaluation import Skills201EvalGateway
from .models import CandidateChange, EvalScore, ExperimentRecord
from .strategy import ProposalLibraryStrategy
from .storage import ExperimentLedger
from .workspace import CandidateWorkspace


class ImprovementStrategy(Protocol):
    def propose_candidates(self) -> tuple[CandidateChange, ...]:
        """Propose bounded change sets."""


class EvalGateway(Protocol):
    def evaluate(self, skills_root: Path) -> EvalScore:
        """Run the eval stack for a candidate workspace."""


class ResearchLoop:
    def __init__(
        self,
        strategy: ImprovementStrategy,
        evaluator: EvalGateway,
        ledger: ExperimentLedger,
        workspace: CandidateWorkspace,
        *,
        baseline_score: float | None = None,
    ):
        self.strategy = strategy
        self.evaluator = evaluator
        self.ledger = ledger
        self.workspace = workspace
        self.baseline_score = baseline_score

    def _resolve_baseline(self) -> float:
        with self.workspace.materialize() as baseline_root:
            source_score = self.evaluator.evaluate(baseline_root).score
        return self.ledger.current_baseline(default=source_score) if self.baseline_score is None else self.baseline_score

    @staticmethod
    def _candidate_rank(record: ExperimentRecord) -> tuple[float, int, int]:
        return (
            record.evaluation.score,
            -len(record.change.patches),
            -len(record.change.target_files),
        )

    def run_once(self) -> ExperimentRecord:
        baseline = self._resolve_baseline()
        candidates = self.strategy.propose_candidates()
        if not candidates:
            raise RuntimeError("No bounded candidates are available for the current target profile.")

        provisional_records: list[ExperimentRecord] = []
        for candidate in candidates:
            with self.workspace.materialize(candidate) as candidate_root:
                evaluation = self.evaluator.evaluate(candidate_root)
            provisional_records.append(
                ExperimentRecord(
                    change=candidate,
                    evaluation=evaluation,
                    accepted=False,
                    baseline_score=baseline,
                    metadata={
                        "candidate_files": len(candidate.target_files),
                        "patch_count": len(candidate.patches),
                        "proposal_kind": candidate.proposal_kind,
                        "datasets": list(evaluation.datasets),
                        "passed_cases": evaluation.passed_cases,
                        "total_cases": evaluation.total_cases,
                    },
                )
            )

        best_record = max(provisional_records, key=self._candidate_rank)
        winner_accepted = (
            best_record.evaluation.passed_gate
            and not best_record.evaluation.security_regressions
            and best_record.evaluation.score > baseline
        )

        final_records: list[ExperimentRecord] = []
        for record in provisional_records:
            accepted = winner_accepted and record.change.change_id == best_record.change.change_id
            final_record = ExperimentRecord(
                change=record.change,
                evaluation=record.evaluation,
                accepted=accepted,
                baseline_score=baseline,
                metadata=record.metadata,
            )
            self.ledger.append(final_record)
            final_records.append(final_record)

        promoted = next(
            record for record in final_records if record.change.change_id == best_record.change.change_id
        )
        if promoted.accepted:
            self.baseline_score = promoted.evaluation.score
        else:
            self.baseline_score = baseline
        return promoted


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single autoresearch iteration.")
    parser.add_argument(
        "--ledger",
        default="experiments/history.jsonl",
        help="Path to the append-only experiment ledger.",
    )
    parser.add_argument("--baseline-score", type=float)
    args = parser.parse_args()

    workspace = CandidateWorkspace(SKILLS_201_PROFILE.root, approved_paths())
    loop = ResearchLoop(
        strategy=ProposalLibraryStrategy(),
        evaluator=Skills201EvalGateway(),
        ledger=ExperimentLedger(Path(args.ledger)),
        workspace=workspace,
        baseline_score=args.baseline_score,
    )
    record = loop.run_once()
    print(
        f"{record.change.change_id}: accepted={record.accepted} "
        f"score={record.evaluation.score:.2f} "
        f"({record.evaluation.passed_cases}/{record.evaluation.total_cases} cases)"
    )


if __name__ == "__main__":
    main()
