from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from autoresearch.config import LLMGenerationConfig, SKILLS_201_PROFILE, TargetProfile, approved_paths
from autoresearch.llm_strategy import LLMProposalStrategy


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


class StaticGenerator:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def generate_json(self, prompt: str) -> dict[str, object]:
        self.prompt = prompt
        return self.payload


class LLMProposalStrategyTests(unittest.TestCase):
    def test_llm_strategy_returns_valid_candidate_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            profile = build_profile_copy(tmp_path)
            old_text = (
                "This is the main `Skills 201` idea:\n\n"
                "- The user speaks naturally\n"
                "- The skills can be composed\n"
                "- The output stays consistent\n"
            )
            new_text = (
                "This is the main `Skills 201` idea:\n\n"
                "- The user speaks naturally\n"
                "- The skills can be composed\n"
                "- The output stays consistent\n"
                "- Keep the routing rules explicit and easy to audit.\n"
            )
            strategy = LLMProposalStrategy(
                StaticGenerator(
                    {
                        "candidates": [
                            {
                                "title": "Clarify bounded surface",
                                "summary": "Reinforce explicit routing guidance in the skills README.",
                                "proposal_kind": "llm-generated",
                                "patches": [
                                    {
                                        "path": "README.md",
                                        "old_text": old_text,
                                        "new_text": new_text,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                profile=profile,
                settings=LLMGenerationConfig(model="gemini-test", api_key_env="TEST_API_KEY"),
                research_program_path=Path(__file__).resolve().parents[1] / "research_program.md",
            )

            candidates = strategy.propose_candidates()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].change_id, "llm-1-clarify-bounded-surface")
        self.assertEqual(candidates[0].target_files, ("README.md",))
        self.assertEqual(candidates[0].metadata["generator_model"], "gemini-test")
        self.assertIn("generator_prompt_sha256", candidates[0].metadata)

    def test_llm_strategy_rejects_paths_outside_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            profile = build_profile_copy(tmp_path)
            strategy = LLMProposalStrategy(
                StaticGenerator(
                    {
                        "candidates": [
                            {
                                "title": "Write somewhere else",
                                "summary": "This should be rejected.",
                                "patches": [
                                    {
                                        "path": "NOT_ALLOWED.md",
                                        "old_text": "old",
                                        "new_text": "new",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                profile=profile,
                settings=LLMGenerationConfig(model="gemini-test", api_key_env="TEST_API_KEY"),
                research_program_path=Path(__file__).resolve().parents[1] / "research_program.md",
            )

            with self.assertRaisesRegex(ValueError, "approved editable surface"):
                strategy.propose_candidates()


if __name__ == "__main__":
    unittest.main()
