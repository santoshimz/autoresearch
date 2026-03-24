from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import LLMGenerationConfig, SKILLS_201_PROFILE, TargetProfile
from .llm import TextGenerator
from .models import CandidateChange, FilePatch


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "candidate"


def _load_profile_sources(profile: TargetProfile) -> dict[str, str]:
    sources: dict[str, str] = {}
    for relative_path in profile.editable_files:
        path = profile.root / relative_path
        sources[relative_path] = path.read_text(encoding="utf-8")
    return sources


@dataclass(frozen=True)
class ValidatedCandidate:
    title: str
    summary: str
    proposal_kind: str
    patches: tuple[FilePatch, ...]


class LLMProposalStrategy:
    def __init__(
        self,
        generator: TextGenerator,
        *,
        profile: TargetProfile = SKILLS_201_PROFILE,
        settings: LLMGenerationConfig,
        research_program_path: Path | None = None,
    ):
        self.generator = generator
        self.profile = profile
        self.settings = settings
        self.research_program_path = research_program_path or profile.root.parents[1] / "research_program.md"

    def _build_prompt(self, file_sources: dict[str, str]) -> str:
        research_program = self.research_program_path.read_text(encoding="utf-8")
        files_json = json.dumps(file_sources, ensure_ascii=True)
        allowed_paths = ", ".join(self.profile.editable_files)
        return (
            "You are generating small, security-preserving documentation improvements for autoresearch.\n"
            "Return JSON only with this shape:\n"
            '{'
            '"candidates": ['
            '{"title": "...", "summary": "...", "proposal_kind": "...", '
            '"patches": [{"path": "...", "old_text": "...", "new_text": "..."}]}'
            "]"
            "}\n"
            "Rules:\n"
            f"- Propose at most {self.settings.max_candidates} candidates.\n"
            f"- Only use these editable paths: {allowed_paths}.\n"
            f"- Each patch must replace an exact existing snippet. Keep replacement text under {self.settings.max_patch_chars} characters.\n"
            "- Keep changes small and text-only.\n"
            "- Do not add SQL, secret storage, credential persistence, or RLS bypass guidance.\n"
            "- Prefer improvements to clarification, routing, composition, and security wording.\n"
            "- Use exact old_text anchors copied from the provided files.\n"
            "- Do not invent new files or paths.\n"
            "Research program:\n"
            f"{research_program}\n\n"
            "Editable file contents as JSON mapping of relative path to file text:\n"
            f"{files_json}"
        )

    def _validate_patch(self, patch_data: dict[str, Any], file_sources: dict[str, str]) -> FilePatch:
        path = str(patch_data["path"])
        if path not in file_sources:
            raise ValueError(f"Patch path {path!r} is not in the approved editable surface.")

        old_text = patch_data["old_text"]
        new_text = patch_data["new_text"]
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ValueError("Patch old_text and new_text must both be strings.")
        if not old_text.strip() or old_text == new_text:
            raise ValueError("Patch old_text must be non-empty and differ from new_text.")
        if len(new_text) > self.settings.max_patch_chars:
            raise ValueError(f"Patch for {path!r} exceeds max_patch_chars.")
        if old_text not in file_sources[path]:
            raise ValueError(f"Patch anchor for {path!r} was not found in the current source text.")
        return FilePatch(path=path, old_text=old_text, new_text=new_text)

    def _validate_candidate(self, candidate_data: dict[str, Any], file_sources: dict[str, str]) -> ValidatedCandidate:
        title = str(candidate_data["title"]).strip()
        summary = str(candidate_data["summary"]).strip()
        proposal_kind = str(candidate_data.get("proposal_kind", "llm-generated")).strip() or "llm-generated"
        patch_rows = candidate_data["patches"]
        if not isinstance(patch_rows, list) or not patch_rows:
            raise ValueError("Candidate patches must be a non-empty list.")

        validated_patches = tuple(self._validate_patch(patch_data, file_sources) for patch_data in patch_rows)
        return ValidatedCandidate(
            title=title or "Untitled candidate",
            summary=summary or "LLM-generated documentation improvement.",
            proposal_kind=proposal_kind,
            patches=validated_patches,
        )

    def propose_candidates(self) -> tuple[CandidateChange, ...]:
        file_sources = _load_profile_sources(self.profile)
        prompt = self._build_prompt(file_sources)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        payload = self.generator.generate_json(prompt)
        candidate_rows = payload.get("candidates")
        if not isinstance(candidate_rows, list) or not candidate_rows:
            raise RuntimeError("LLM candidate generation returned no candidates.")

        validated_candidates: list[CandidateChange] = []
        seen_ids: set[str] = set()
        for index, candidate_row in enumerate(candidate_rows[: self.settings.max_candidates], start=1):
            validated = self._validate_candidate(candidate_row, file_sources)
            change_id = f"llm-{index}-{_slugify(validated.title)}"
            if change_id in seen_ids:
                continue
            seen_ids.add(change_id)
            validated_candidates.append(
                CandidateChange(
                    change_id=change_id,
                    title=validated.title,
                    target_files=tuple(dict.fromkeys(patch.path for patch in validated.patches)),
                    summary=validated.summary,
                    proposal_kind=validated.proposal_kind,
                    patches=validated.patches,
                    metadata={
                        "generator_provider": self.settings.provider,
                        "generator_model": self.settings.model,
                        "generator_prompt_sha256": prompt_hash,
                    },
                )
            )

        if not validated_candidates:
            raise RuntimeError("LLM candidate generation did not produce any valid approved candidates.")
        return tuple(validated_candidates)
