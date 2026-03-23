from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SKILLS_201_PROFILE, TargetProfile
from .models import CandidateChange, FilePatch


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_patch(path: Path, old_text: str, new_text: str, *, root: Path) -> FilePatch | None:
    current = _read_text(path)
    if new_text in current:
        return None
    if old_text not in current:
        raise ValueError(f"Could not find patch anchor in {path}.")
    return FilePatch(path=str(path.relative_to(root)), old_text=old_text, new_text=new_text)


@dataclass
class ProposalLibraryStrategy:
    profile: TargetProfile = SKILLS_201_PROFILE

    def _skills_path(self, relative_path: str) -> Path:
        return self.profile.root / relative_path

    def _clarification_candidate(self) -> CandidateChange | None:
        readme_path = self._skills_path("README.md")
        anchor = (
            "For folder-based workflows:\n\n"
            "```text\n"
            "Use the images in `examples` as the source folder, apply the crop workflow to every "
            "source image, then colorize the results and keep the originals.\n"
            "```\n\n"
        )
        insertion = (
            anchor
            + "If a request is ambiguous or only says to make an image better, clarify instead of guessing.\n\n"
            + "```text\n"
            + "Make this better without changing the people in the scene.\n"
            + "```\n\n"
            + "Ask a follow-up question that narrows the request to cropping, colorization, or both.\n\n"
        )
        patch = _make_patch(readme_path, anchor, insertion, root=self.profile.root)
        if patch is None:
            return None
        return CandidateChange(
            change_id="clarify-example-readme",
            title="Add clarification example to README",
            target_files=(patch.path,),
            summary="Teach the skill surface to clarify ambiguous improvement requests instead of guessing.",
            proposal_kind="clarification-example",
            patches=(patch,),
        )

    def _credential_candidate(self) -> CandidateChange | None:
        patches: list[FilePatch] = []
        anchor = (
            "## Guardrails\n\n"
            "- Never log API keys.\n"
            "- Fail clearly when `GEMINI_API_KEY` is missing.\n"
            "- Keep automated tests mocked instead of calling the live API.\n"
            "- Preserve framing and scene details unless the user explicitly asks for creative changes.\n"
        )
        replacement = (
            "## Guardrails\n\n"
            "- Never log API keys.\n"
            "- Use any BYOK key only for the active run and do not save it anywhere.\n"
            "- Fail clearly when `GEMINI_API_KEY` is missing.\n"
            "- Keep automated tests mocked instead of calling the live API.\n"
            "- Preserve framing and scene details unless the user explicitly asks for creative changes.\n"
        )
        for relative_path in (
            ".agents/skills/colorize-images/SKILL.md",
            ".cursor/skills/colorize-images/SKILL.md",
        ):
            patch = _make_patch(self._skills_path(relative_path), anchor, replacement, root=self.profile.root)
            if patch is not None:
                patches.append(patch)
        if not patches:
            return None
        return CandidateChange(
            change_id="credential-guardrail-colorize-skill",
            title="Tighten BYOK guidance in colorize skill",
            target_files=tuple(patch.path for patch in patches),
            summary="Clarify that BYOK credentials stay ephemeral and must never be persisted or logged.",
            proposal_kind="security-example",
            patches=tuple(patches),
        )

    def _composition_candidate(self) -> CandidateChange | None:
        patches: list[FilePatch] = []
        anchor = (
            "## Workflow\n\n"
            "This is a meta-skill. Do not jump straight to `src/process_bw_images.py` when the point is "
            "to demonstrate multi-skill composition.\n\n"
        )
        replacement = (
            "## Workflow\n\n"
            "This is a meta-skill. Do not jump straight to `src/process_bw_images.py` when the point is "
            "to demonstrate multi-skill composition.\n\n"
            "Use this path when the user asks for both cleanup/cropping and realistic colorization in one request.\n\n"
        )
        for relative_path in (
            ".agents/skills/process-bw-images/SKILL.md",
            ".cursor/skills/process-bw-images/SKILL.md",
        ):
            patch = _make_patch(self._skills_path(relative_path), anchor, replacement, root=self.profile.root)
            if patch is not None:
                patches.append(patch)
        if not patches:
            return None
        return CandidateChange(
            change_id="composition-guidance-process-skill",
            title="Strengthen crop-then-colorize routing guidance",
            target_files=tuple(patch.path for patch in patches),
            summary="Make the end-to-end composition rule more explicit for prompts that request both steps.",
            proposal_kind="tool-selection-guidance",
            patches=tuple(patches),
        )

    def _tool_selection_candidate(self) -> CandidateChange | None:
        readme_path = self._skills_path("README.md")
        anchor = (
            "This is the main `Skills 201` idea:\n\n"
            "- The user speaks naturally\n"
            "- The skills can be composed\n"
            "- The output stays consistent\n"
        )
        replacement = (
            "This is the main `Skills 201` idea:\n\n"
            "- The user speaks naturally\n"
            "- The skills can be composed\n"
            "- The output stays consistent\n"
            "- Route crop-only requests to `cropping-images`, color-only requests to `colorize-images`, "
            "and combined requests to the composed workflow.\n"
        )
        patch = _make_patch(readme_path, anchor, replacement, root=self.profile.root)
        if patch is None:
            return None
        return CandidateChange(
            change_id="tool-selection-readme",
            title="Add explicit routing guidance to README",
            target_files=(patch.path,),
            summary="State the crop-only, color-only, and combined routing rules in one place.",
            proposal_kind="tool-selection-guidance",
            patches=(patch,),
        )

    def propose_candidates(self) -> tuple[CandidateChange, ...]:
        candidates = (
            self._clarification_candidate(),
            self._credential_candidate(),
            self._composition_candidate(),
            self._tool_selection_candidate(),
        )
        return tuple(candidate for candidate in candidates if candidate is not None)
