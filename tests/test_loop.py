from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from autoresearch.config import SKILLS_201_PROFILE, TargetProfile, approved_paths
from autoresearch.evaluation import Skills201EvalGateway
from autoresearch.loop import ResearchLoop
from autoresearch.storage import ExperimentLedger
from autoresearch.strategy import ProposalLibraryStrategy
from autoresearch.workspace import CandidateWorkspace


def build_profile_copy(tmp_dir: Path) -> TargetProfile:
    copied_root = tmp_dir / "skills-201"
    for source_path in approved_paths(SKILLS_201_PROFILE):
        relative_path = source_path.relative_to(SKILLS_201_PROFILE.root)
        destination_path = copied_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
    return TargetProfile(
        name="skills-201-test",
        root=copied_root,
        editable_files=SKILLS_201_PROFILE.editable_files,
    )


class ResearchLoopTests(unittest.TestCase):
    def test_clarification_candidate_improves_nightly_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = build_profile_copy(Path(tmp_dir))
            strategy = ProposalLibraryStrategy(profile=profile)
            evaluator = Skills201EvalGateway()
            workspace = CandidateWorkspace(profile.root, approved_paths(profile))

            baseline_score = evaluator.evaluate(profile.root)
            self.assertTrue(baseline_score.passed_gate)
            self.assertLess(baseline_score.score, 1.0)

            clarification_candidate = next(
                candidate for candidate in strategy.propose_candidates() if candidate.change_id == "clarify-example-readme"
            )
            with workspace.materialize(clarification_candidate) as candidate_root:
                improved_score = evaluator.evaluate(candidate_root)

        self.assertGreater(improved_score.score, baseline_score.score)
        self.assertEqual(improved_score.score, 1.0)

    def test_loop_promotes_best_candidate_and_records_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            profile = build_profile_copy(tmp_path)
            loop = ResearchLoop(
                strategy=ProposalLibraryStrategy(profile=profile),
                evaluator=Skills201EvalGateway(),
                ledger=ExperimentLedger(tmp_path / "history.jsonl"),
                workspace=CandidateWorkspace(profile.root, approved_paths(profile)),
            )
            record = loop.run_once()
            history = ExperimentLedger(tmp_path / "history.jsonl").read_records()

        self.assertTrue(record.accepted)
        self.assertEqual(record.change.change_id, "clarify-example-readme")
        self.assertGreaterEqual(len(history), 3)
        self.assertEqual(sum(1 for item in history if item["accepted"]), 1)


if __name__ == "__main__":
    unittest.main()
