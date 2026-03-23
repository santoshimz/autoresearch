from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RequestField:
    name: str
    required: bool
    secret: bool = False
    notes: str = ""


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    request_fields: tuple[RequestField, ...]
    selected_workflow_field: str | None = None


@dataclass(frozen=True)
class SecurityContract:
    max_images: int
    max_file_size_bytes: int
    auth_header: str
    server_key_env: str
    byok_field: str
    forbidden_log_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BaselineContract:
    repo: str
    workflows: tuple[str, ...]
    tools: tuple[ToolContract, ...]
    security: SecurityContract


MCP101_BASELINE = BaselineContract(
    repo="mcp-101",
    workflows=("crop_images", "colorize_images", "crop_then_colorize"),
    tools=(
        ToolContract(
            name="crop_images",
            description="Crop uploaded screenshots or images to the visible frame.",
            request_fields=(
                RequestField("images", required=True, notes="1-5 images; base64 encoded image payloads"),
            ),
        ),
        ToolContract(
            name="colorize_images",
            description="Colorize uploaded images with either server credentials or BYOK.",
            request_fields=(
                RequestField("images", required=True),
                RequestField("credential_mode", required=False, notes="server or byok"),
                RequestField("gemini_api_key", required=False, secret=True),
                RequestField("prompt", required=False),
                RequestField("model", required=False),
            ),
        ),
        ToolContract(
            name="run_prompt_workflow",
            description="Interpret a natural-language prompt and route to the correct workflow.",
            request_fields=(
                RequestField("prompt", required=True),
                RequestField("images", required=True),
                RequestField("credential_mode", required=False, notes="server or byok"),
                RequestField("gemini_api_key", required=False, secret=True),
                RequestField("model", required=False),
            ),
            selected_workflow_field="selected_workflow",
        ),
    ),
    security=SecurityContract(
        max_images=5,
        max_file_size_bytes=6 * 1024 * 1024,
        auth_header="Authorization: Bearer <token>",
        server_key_env="MCP_101_SERVER_GEMINI_API_KEY",
        byok_field="geminiApiKey",
        forbidden_log_fields=("gemini_api_key", "geminiApiKey", "authorization"),
    ),
)


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    checks: dict[str, bool]
    messages: list[str]


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    raise TypeError(f"Unsupported tool sequence type: {type(value)!r}")


def grade_case(case: dict[str, Any], result: dict[str, Any]) -> GradeResult:
    checks: dict[str, bool] = {}
    messages: list[str] = []

    expected_workflow = case.get("expected_workflow")
    actual_workflow = result.get("selected_workflow") or result.get("workflow")
    checks["workflow_match"] = actual_workflow == expected_workflow
    if not checks["workflow_match"]:
        messages.append(f"Expected workflow {expected_workflow!r}, got {actual_workflow!r}.")

    expected_tool_sequence = _as_set(case.get("expected_tool_sequence"))
    actual_tool_sequence = _as_set(result.get("tool_sequence"))
    checks["tool_sequence_match"] = not expected_tool_sequence or actual_tool_sequence == expected_tool_sequence
    if not checks["tool_sequence_match"]:
        messages.append(
            f"Expected tool sequence {sorted(expected_tool_sequence)!r}, got {sorted(actual_tool_sequence)!r}."
        )

    output_count = result.get("output_count")
    if "expected_output_count" in case:
        checks["output_count_match"] = output_count == case["expected_output_count"]
        if not checks["output_count_match"]:
            messages.append(
                f"Expected output_count {case['expected_output_count']!r}, got {output_count!r}."
            )

    return GradeResult(passed=all(checks.values()) if checks else True, checks=checks, messages=messages)


def grade_security_expectations(report: dict[str, Any]) -> GradeResult:
    checks = {
        "no_secret_logs": True,
        "image_limit_respected": report.get("image_count", 0) <= MCP101_BASELINE.security.max_images,
    }
    messages: list[str] = []

    logs = " ".join(str(part) for part in report.get("log_lines", []))
    for forbidden_field in MCP101_BASELINE.security.forbidden_log_fields:
        if forbidden_field in logs:
            checks["no_secret_logs"] = False
            messages.append(f"Forbidden field {forbidden_field!r} appeared in logs.")

    if not checks["image_limit_respected"]:
        messages.append(f"Image count exceeded {MCP101_BASELINE.security.max_images}.")

    return GradeResult(passed=all(checks.values()), checks=checks, messages=messages)


class WorkflowSystem(Protocol):
    def run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Execute a single evaluation case."""


@dataclass
class EvaluationReport:
    system_name: str
    dataset_path: Path
    total_cases: int
    passed_cases: int
    case_results: list[GradeResult]
    security_result: GradeResult


def load_cases(dataset_path: str | Path) -> list[dict[str, Any]]:
    path = Path(dataset_path)
    return json.loads(path.read_text(encoding="utf-8"))


class BaseRunner:
    system_name = "base"

    def __init__(self, system: WorkflowSystem):
        self.system = system

    def evaluate(self, dataset_path: str | Path) -> EvaluationReport:
        cases = load_cases(dataset_path)
        case_results: list[GradeResult] = []
        aggregate_report = {"image_count": 0, "log_lines": []}
        for case in cases:
            result = self.system.run_case(case)
            case_results.append(grade_case(case, result))
            aggregate_report["image_count"] = max(aggregate_report["image_count"], result.get("image_count", 0))
            aggregate_report["log_lines"].extend(result.get("log_lines", []))

        security_result = grade_security_expectations(aggregate_report)
        return EvaluationReport(
            system_name=self.system_name,
            dataset_path=Path(dataset_path),
            total_cases=len(case_results),
            passed_cases=sum(1 for case in case_results if case.passed),
            case_results=case_results,
            security_result=security_result,
        )


class Skills201Runner(BaseRunner):
    system_name = "skills-201"
