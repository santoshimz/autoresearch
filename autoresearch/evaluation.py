from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import SKILLS_201_GATE_DATASET, SKILLS_201_NIGHTLY_DATASET
from .evals import MCP101_BASELINE, Skills201Runner
from .models import EvalScore


CROP_PATTERNS = (r"\bcrop\b", r"visible frame", r"trim", r"screenshot", r"clean")
COLORIZE_PATTERNS = (
    r"\bcolori[sz]e\b",
    r"\bcolori[sz]ation\b",
    r"black[\s-]and[\s-]white",
    r"restore color",
    r"add color",
)
AMBIGUOUS_PATTERNS = (r"make this better", r"improve", r"without changing")
CLARIFY_TERMS = ("clarify", "follow-up question", "instead of guessing", "ambiguous")
SECURITY_BAD_PATTERNS = ("save api key", "store api key", "persist key", "bypass rls")


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


@dataclass
class SkillCorpus:
    crop_text: str
    colorize_text: str
    process_text: str
    readme_text: str
    full_text: str


class Skills201WorkflowSystem:
    def __init__(self, skills_root: Path):
        self.skills_root = skills_root
        self.corpus = self._load_corpus()

    def _load_corpus(self) -> SkillCorpus:
        paths = {
            "crop_text": self.skills_root / ".agents/skills/cropping-images/SKILL.md",
            "colorize_text": self.skills_root / ".agents/skills/colorize-images/SKILL.md",
            "process_text": self.skills_root / ".agents/skills/process-bw-images/SKILL.md",
            "readme_text": self.skills_root / "README.md",
        }
        values = {name: _normalize(path.read_text(encoding="utf-8")) for name, path in paths.items()}
        full_text = " ".join(values.values())
        return SkillCorpus(full_text=full_text, **values)

    def _supports_clarification(self) -> bool:
        return all(term in self.corpus.full_text for term in CLARIFY_TERMS[:2]) or any(
            term in self.corpus.full_text for term in CLARIFY_TERMS
        )

    def _has_security_regression(self) -> list[str]:
        regressions: list[str] = []
        for pattern in SECURITY_BAD_PATTERNS:
            if pattern in self.corpus.full_text:
                regressions.append(f"Documentation introduced forbidden guidance: {pattern!r}.")
        return regressions

    def _route_prompt(self, prompt: str) -> str | None:
        normalized = _normalize(prompt)
        has_crop = _matches_any(normalized, CROP_PATTERNS) and "crop" in self.corpus.crop_text
        has_colorize = _matches_any(normalized, COLORIZE_PATTERNS) and "color" in self.corpus.colorize_text

        if not has_crop and not has_colorize and _matches_any(normalized, AMBIGUOUS_PATTERNS):
            if self._supports_clarification():
                return "clarify"
            return None

        if has_crop and has_colorize and "meta-skill" in self.corpus.process_text:
            return "crop_then_colorize"
        if has_crop:
            return "crop_images"
        if has_colorize:
            return "colorize_images"
        return None

    def run_case(self, case: dict[str, object]) -> dict[str, object]:
        prompt = str(case.get("prompt", ""))
        workflow = self._route_prompt(prompt)
        tool_sequence_map = {
            "crop_images": ["crop_images"],
            "colorize_images": ["colorize_images"],
            "crop_then_colorize": ["crop_images", "colorize_images"],
            "clarify": [],
            None: [],
        }
        output_count_map = {
            "crop_images": 1,
            "colorize_images": 1,
            "crop_then_colorize": 2,
            "clarify": 0,
            None: 0,
        }
        logs = list(self._has_security_regression())
        if "byok" in _normalize(prompt) and "do not save" in _normalize(prompt):
            logs.append("byok flow handled without persistence")
        return {
            "workflow": workflow,
            "selected_workflow": workflow,
            "tool_sequence": tool_sequence_map[workflow],
            "output_count": output_count_map[workflow],
            "image_count": int(case.get("image_count", 0)),
            "log_lines": logs,
        }


def collect_alignment_messages(skills_root: Path) -> tuple[str, ...]:
    crop_text = _normalize((skills_root / ".agents/skills/cropping-images/SKILL.md").read_text(encoding="utf-8"))
    colorize_text = _normalize((skills_root / ".agents/skills/colorize-images/SKILL.md").read_text(encoding="utf-8"))
    messages: list[str] = []

    crop_description = _normalize(MCP101_BASELINE.tools[0].description)
    colorize_description = _normalize(MCP101_BASELINE.tools[1].description)
    if "visible frame" not in crop_text and "visible frame" in crop_description:
        messages.append("Crop skill docs drifted away from the visible-frame baseline wording.")
    if "preserve" not in colorize_text and "colorize" in colorize_description:
        messages.append("Colorize skill docs no longer emphasize preservation and realistic colorization.")
    return tuple(messages)


class Skills201EvalGateway:
    def evaluate(self, skills_root: Path) -> EvalScore:
        system = Skills201WorkflowSystem(skills_root)
        runner = Skills201Runner(system)
        gate_report = runner.evaluate(SKILLS_201_GATE_DATASET)
        gate_passed = gate_report.passed_cases == gate_report.total_cases and gate_report.security_result.passed

        reports = [gate_report]
        notes = [
            f"Gate dataset: {gate_report.passed_cases}/{gate_report.total_cases} cases passed.",
        ]
        if gate_passed:
            nightly_report = runner.evaluate(SKILLS_201_NIGHTLY_DATASET)
            reports.append(nightly_report)
            notes.append(f"Nightly dataset: {nightly_report.passed_cases}/{nightly_report.total_cases} cases passed.")
        else:
            notes.append("Nightly dataset skipped because the gate dataset did not fully pass.")

        alignment_messages = collect_alignment_messages(skills_root)
        notes.extend(alignment_messages)

        security_regressions: list[str] = []
        passed_cases = 0
        total_cases = 0
        for report in reports:
            passed_cases += report.passed_cases
            total_cases += report.total_cases
            if not report.security_result.passed:
                security_regressions.extend(report.security_result.messages)

        score = passed_cases / total_cases if total_cases else 0.0
        dataset_names = tuple(report.dataset_path.name for report in reports)
        return EvalScore(
            passed_gate=gate_passed,
            score=score,
            security_regressions=tuple(security_regressions),
            notes=tuple(notes),
            datasets=dataset_names,
            passed_cases=passed_cases,
            total_cases=total_cases,
        )
