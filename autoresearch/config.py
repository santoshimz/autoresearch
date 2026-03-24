from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _discover_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / "targets").exists() and (package_root / "datasets").exists():
        return package_root

    cwd_root = Path.cwd().resolve()
    if (cwd_root / "targets").exists() and (cwd_root / "datasets").exists():
        return cwd_root

    return package_root


AUTORESEARCH_ROOT = _discover_root()
TARGETS_ROOT = AUTORESEARCH_ROOT / "targets"
DATASETS_ROOT = AUTORESEARCH_ROOT / "datasets"
SKILLS_201_ROOT = TARGETS_ROOT / "skills-201"
MCP_201_ROOT = TARGETS_ROOT / "mcp-201-prompts"

SKILLS_201_GATE_DATASET = DATASETS_ROOT / "gate" / "skills_201_workflow_routing.json"
SKILLS_201_NIGHTLY_DATASET = DATASETS_ROOT / "nightly" / "skills_201_tool_use.json"


@dataclass(frozen=True)
class TargetProfile:
    name: str
    root: Path
    editable_files: tuple[str, ...]


@dataclass(frozen=True)
class LLMGenerationConfig:
    provider: str = "gemini"
    model: str = "gemini-2.0-flash"
    api_key_env: str = "AUTORESEARCH_GEMINI_API_KEY"
    max_candidates: int = 4
    max_patch_chars: int = 1600


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
    root=MCP_201_ROOT,
    editable_files=(
        "server/prompt_text.py",
        "server/prompt_planner.py",
        "skills/colorize_images.py",
        "mcp_201_server.py",
    ),
)


def approved_paths(profile: TargetProfile = SKILLS_201_PROFILE) -> tuple[Path, ...]:
    return tuple(profile.root / relative_path for relative_path in profile.editable_files)


def load_llm_generation_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    max_candidates: int | None = None,
    max_patch_chars: int | None = None,
) -> LLMGenerationConfig:
    return LLMGenerationConfig(
        provider=provider if provider is not None else os.getenv("AUTORESEARCH_LLM_PROVIDER", LLMGenerationConfig.provider),
        model=model if model is not None else os.getenv("AUTORESEARCH_LLM_MODEL", LLMGenerationConfig.model),
        api_key_env=(
            api_key_env
            if api_key_env is not None
            else os.getenv("AUTORESEARCH_LLM_API_KEY_ENV", LLMGenerationConfig.api_key_env)
        ),
        max_candidates=max_candidates if max_candidates is not None else int(
            os.getenv("AUTORESEARCH_LLM_MAX_CANDIDATES", str(LLMGenerationConfig.max_candidates))
        ),
        max_patch_chars=max_patch_chars if max_patch_chars is not None else int(
            os.getenv("AUTORESEARCH_LLM_MAX_PATCH_CHARS", str(LLMGenerationConfig.max_patch_chars))
        ),
    )
