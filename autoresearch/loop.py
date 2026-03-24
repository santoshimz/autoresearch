from __future__ import annotations

import argparse
from pathlib import Path
from typing import Protocol

from .config import SKILLS_201_PROFILE, approved_paths, load_llm_generation_config
from .evaluation import Skills201EvalGateway
from .llm import GeminiTextGenerator
from .llm_strategy import LLMProposalStrategy
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
                    metadata=self._build_record_metadata(candidate, evaluation),
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

    def _build_record_metadata(self, candidate: CandidateChange, evaluation: EvalScore) -> dict[str, object]:
        metadata: dict[str, object] = {
            "strategy_name": type(self.strategy).__name__,
            "candidate_files": len(candidate.target_files),
            "patch_count": len(candidate.patches),
            "proposal_kind": candidate.proposal_kind,
            "datasets": list(evaluation.datasets),
            "passed_cases": evaluation.passed_cases,
            "total_cases": evaluation.total_cases,
        }
        for key, value in candidate.metadata.items():
            metadata.setdefault(key, value)
        return metadata


def build_strategy(args: argparse.Namespace):
    profile = SKILLS_201_PROFILE
    if args.strategy == "llm":
        settings = load_llm_generation_config(
            provider=args.llm_provider,
            model=args.llm_model,
            api_key_env=args.llm_api_key_env,
            max_candidates=args.llm_max_candidates,
            max_patch_chars=args.llm_max_patch_chars,
        )
        if settings.provider != "gemini":
            raise ValueError(f"Unsupported LLM provider {settings.provider!r}.")
        return LLMProposalStrategy(
            GeminiTextGenerator(model=settings.model, api_key_env=settings.api_key_env),
            profile=profile,
            settings=settings,
        )
    return ProposalLibraryStrategy(profile=profile)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single autoresearch iteration.")
    parser.add_argument(
        "--ledger",
        default="experiments/history.jsonl",
        help="Path to the append-only experiment ledger.",
    )
    parser.add_argument("--baseline-score", type=float)
    parser.add_argument("--strategy", choices=("library", "llm"), default="library")
    parser.add_argument("--llm-provider")
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-api-key-env")
    parser.add_argument("--llm-max-candidates", type=int)
    parser.add_argument("--llm-max-patch-chars", type=int)
    args = parser.parse_args()

    workspace = CandidateWorkspace(SKILLS_201_PROFILE.root, approved_paths())
    loop = ResearchLoop(
        strategy=build_strategy(args),
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
