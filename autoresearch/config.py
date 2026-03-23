from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
AUTORESEARCH_ROOT = WORKSPACE_ROOT / "autoresearch"
SKILLS_201_ROOT = WORKSPACE_ROOT / "skills-201"
EVALS_101_ROOT = WORKSPACE_ROOT / "evals-101"
MCP_201_ROOT = WORKSPACE_ROOT / "mcp-201"

SKILLS_201_GATE_DATASET = EVALS_101_ROOT / "datasets/gate/skills_201_workflow_routing.json"
SKILLS_201_NIGHTLY_DATASET = EVALS_101_ROOT / "datasets/nightly/skills_201_tool_use.json"


@dataclass(frozen=True)
class TargetProfile:
    name: str
    root: Path
    editable_files: tuple[str, ...]


SKILLS_201_PROFILE = TargetProfile(
    name="skills-201",
    root=SKILLS_201_ROOT,
    editable_files=(
        "README.md",
        ".agents/skills/cropping-images/SKILL.md",
        ".agents/skills/colorize-images/SKILL.md",
        ".agents/skills/process-bw-images/SKILL.md",
        ".cursor/skills/cropping-images/SKILL.md",
        ".cursor/skills/colorize-images/SKILL.md",
        ".cursor/skills/process-bw-images/SKILL.md",
    ),
)

MCP_201_PROMPT_PROFILE = TargetProfile(
    name="mcp-201-prompts",
    root=MCP_201_ROOT / "backend" / "src",
    editable_files=(
        "server/prompt_text.py",
        "server/prompt_planner.py",
        "skills/colorize_images.py",
        "mcp_201_server.py",
    ),
)


def approved_paths(profile: TargetProfile = SKILLS_201_PROFILE) -> tuple[Path, ...]:
    return tuple(profile.root / relative_path for relative_path in profile.editable_files)
