"""Deterministic, offline RC6 technical-pilot orchestration for frozen cases T01-T24.

The runner reuses the merged RC3 discovery, RC4 validation, RC5 reuse-evidence,
issue-readiness, and report-rendering interfaces. It never mutates the registry,
readiness state, GitHub metadata, repository sources, or external systems. The
only writes are caller-directed JSON and Markdown result artifacts.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

RUNNER_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_SRC = RUNNER_ROOT / "08_Tooling" / "reusable-capability-registry" / "src"
if str(REGISTRY_SRC) not in sys.path:
    sys.path.insert(0, str(REGISTRY_SRC))

from .execution import execute_case

FROZEN_SHA = "ca980c38d74b8d3ab30ca67461a9f576281edc75"
PACKAGE_VERSION = "RC6-TF-1.0"
FIXTURE_SHA256 = "336158b346e2c954b88fa7e3060098e6aabd4237cfb18c4b5df77ef39b5c8186"
EXPECTED_IDS = tuple(f"T{number:02d}" for number in range(1, 25))
DEFAULT_FIXTURE = RUNNER_ROOT / "tests" / "fixtures" / "rc6_technical_pilot" / "cases.json"

_REQUIRED_EXPECTED_FIELDS = frozenset(
    {
        "rc3_ids",
        "rc3_confidence",
        "rc3_evidence_basis",
        "rc3_manual_review_reasons",
        "rc3_warnings",
        "rc3_boundary",
        "rc4_severity",
        "rc4_finding_codes",
        "provenance_states",
        "rc5_statuses",
        "rc5_evidence_disposition",
        "positive_guidance",
        "readiness_before",
        "readiness_after",
        "implementation_authorized",
        "repository_write_authorized",
        "merge_authorized",
        "automatic_selection",
        "active_exemption_reviewed",
    }
)
_REQUIRED_CASE_FIELDS = frozenset(
    {
        "case_id",
        "source_comment_id",
        "source_type",
        "category",
        "strategy",
        "readiness_input",
        "scenario",
        "sample_rationale",
        "sanitized_input",
        "fixture_reference",
        "expected",
        "threshold_classes",
    }
)


class FixtureContractError(ValueError):
    """Raised when the frozen package is missing, reordered, altered, or ambiguous."""


class PilotExecutionError(RuntimeError):
    """Raised when the runner cannot safely execute the frozen package."""


@dataclass(frozen=True)
class PilotRun:
    payload: dict[str, Any]
    json_bytes: bytes
    markdown: str

    @property
    def passed(self) -> bool:
        return self.payload["overall_result"] == "pass"

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


def load_frozen_package(path: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture_path = Path(path)
    raw = fixture_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FIXTURE_SHA256:
        raise FixtureContractError(
            f"fixture digest mismatch: expected {FIXTURE_SHA256}, observed {digest}"
        )
    try:
        package = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureContractError("fixture must be valid UTF-8 JSON") from exc
    validate_frozen_package(package)
    return package


def validate_frozen_package(package: Mapping[str, Any]) -> None:
    if package.get("package_version") != PACKAGE_VERSION:
        raise FixtureContractError("package_version must be RC6-TF-1.0")
    if package.get("frozen_sha") != FROZEN_SHA:
        raise FixtureContractError("fixture frozen_sha does not match the binding baseline")
    cases = package.get("cases")
    if not isinstance(cases, list):
        raise FixtureContractError("cases must be a list")
    ids = tuple(case.get("case_id") for case in cases if isinstance(case, Mapping))
    if ids != EXPECTED_IDS:
        raise FixtureContractError(
            "case IDs must be exactly T01-T24 in binding order; missing, duplicate, extra, "
            "or reordered IDs are rejected"
        )
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, Mapping):
            raise FixtureContractError(f"T{index:02d} must be a mapping")
        missing = sorted(_REQUIRED_CASE_FIELDS - set(case))
        if missing:
            raise FixtureContractError(f"{case['case_id']} missing fields: {', '.join(missing)}")
        expected = case.get("expected")
        if not isinstance(expected, Mapping):
            raise FixtureContractError(f"{case['case_id']} expected must be a mapping")
        missing_expected = sorted(_REQUIRED_EXPECTED_FIELDS - set(expected))
        if missing_expected:
            raise FixtureContractError(
                f"{case['case_id']} expected missing fields: {', '.join(missing_expected)}"
            )
        if _contains_actual_field(case):
            raise FixtureContractError(
                f"{case['case_id']} frozen input must not contain actual-result fields"
            )
    thresholds = package.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise FixtureContractError("thresholds must be a mapping")
    expected_thresholds = {
        "false_positive_recommendations_max": 0,
        "false_negatives_clean_cases_max": 0,
        "unexpected_manual_review_clean_cases_max": 0,
        "false_implementation_authorizations_max": 0,
        "false_repository_write_authorizations_max": 0,
        "false_merge_authorizations_max": 0,
        "silent_automatic_selection_max": 0,
        "deterministic_cases_required": 24,
        "contradicted_evidence_used_positively_max": 0,
        "missing_active_path_used_positively_max": 0,
        "active_exemptions_reviewed_percent_min": 100,
    }
    if dict(thresholds) != expected_thresholds:
        raise FixtureContractError("frozen thresholds or denominators were changed")


def _contains_actual_field(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).startswith("actual_"):
                return True
            if _contains_actual_field(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_actual_field(item) for item in value)
    return False


def validate_exact_sha(supplied_sha: str, actual_head_sha: str) -> None:
    if supplied_sha != FROZEN_SHA:
        raise PilotExecutionError(
            f"supplied SHA must equal frozen SHA {FROZEN_SHA}; observed {supplied_sha}"
        )
    if actual_head_sha != FROZEN_SHA:
        raise PilotExecutionError(
            f"tested checkout must equal frozen SHA {FROZEN_SHA}; observed {actual_head_sha}"
        )


def resolve_git_head(repository_root: str | Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(repository_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PilotExecutionError("unable to resolve tested checkout SHA")
    return completed.stdout.strip()


def run_pilot(
    repository_root: str | Path,
    *,
    supplied_sha: str,
    actual_head_sha: str | None = None,
    fixture_path: str | Path = DEFAULT_FIXTURE,
    runner_sha: str | None = None,
) -> PilotRun:
    root = Path(repository_root).resolve()
    package = load_frozen_package(fixture_path)
    tested_sha = actual_head_sha or resolve_git_head(root)
    validate_exact_sha(supplied_sha, tested_sha)

    case_payloads: list[dict[str, Any]] = []
    for case in package["cases"]:
        first = execute_case(case, root)
        second = execute_case(case, root)
        first_bytes = canonical_json_bytes(first)
        second_bytes = canonical_json_bytes(second)
        deterministic = first_bytes == second_bytes
        actual = dict(first)
        actual["repeat_output_digest_1"] = hashlib.sha256(first_bytes).hexdigest()
        actual["repeat_output_digest_2"] = hashlib.sha256(second_bytes).hexdigest()
        actual["deterministic"] = deterministic
        differences = compare_expected(case["expected"], actual)
        case_payloads.append(
            {
                "case_id": case["case_id"],
                "source_type": case["source_type"],
                "category": case["category"],
                "source_comment_id": case["source_comment_id"],
                "expected": case["expected"],
                "actual": actual,
                "differences": differences,
                "case_result": "pass" if deterministic and not differences else "fail",
            }
        )

    metrics = calculate_metrics(package, case_payloads)
    threshold_results = apply_thresholds(package["thresholds"], metrics)
    all_cases_pass = all(item["case_result"] == "pass" for item in case_payloads)
    all_thresholds_pass = all(item["result"] == "pass" for item in threshold_results.values())
    payload = {
        "schema_version": "1.0",
        "package_version": package["package_version"],
        "fixture_sha256": FIXTURE_SHA256,
        "runner_sha": runner_sha or "unrecorded",
        "tested_sha": tested_sha,
        "case_total": len(case_payloads),
        "case_passed": sum(item["case_result"] == "pass" for item in case_payloads),
        "case_failed": sum(item["case_result"] == "fail" for item in case_payloads),
        "metrics": metrics,
        "threshold_results": threshold_results,
        "authorization": {
            "implementation_authorized": False,
            "repository_write_authorized": False,
            "merge_authorized": False,
            "automatic_selection_performed": False,
        },
        "overall_result": "pass" if all_cases_pass and all_thresholds_pass else "fail",
        "cases": case_payloads,
    }
    json_bytes = canonical_json_bytes(payload) + b"\n"
    markdown = render_markdown_summary(payload)
    return PilotRun(payload=payload, json_bytes=json_bytes, markdown=markdown)


def write_artifacts(run: PilotRun, output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "rc6-technical-pilot.json"
    markdown_path = target / "rc6-technical-pilot.md"
    json_path.write_bytes(run.json_bytes)
    markdown_path.write_text(run.markdown, encoding="utf-8", newline="\n")
    return json_path, markdown_path


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compare_expected(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    for key in sorted(_REQUIRED_EXPECTED_FIELDS):
        if actual.get(key) != expected.get(key):
            differences.append(
                f"{key}: expected={expected.get(key)!r}; actual={actual.get(key)!r}"
            )
    return differences


def calculate_metrics(
    package: Mapping[str, Any], case_payloads: list[Mapping[str, Any]]
) -> dict[str, Any]:
    by_id = {item["case_id"]: item for item in case_payloads}
    false_positive_cases = [
        case["case_id"]
        for case in package["cases"]
        if not case["expected"]["positive_guidance"]
        and by_id[case["case_id"]]["actual"]["positive_guidance"]
    ]
    clean_ids = ["T01", "T21", "T22", "T23", "T24"]
    false_negative_cases = [
        case_id for case_id in clean_ids if not by_id[case_id]["actual"]["positive_guidance"]
    ]
    unexpected_manual_review_cases = [
        case_id
        for case_id in clean_ids
        if "manual-review" in by_id[case_id]["actual"]["rc5_statuses"]
    ]
    deterministic = sum(bool(item["actual"]["deterministic"]) for item in case_payloads)
    active_exemption_ids = [
        case["case_id"]
        for case in package["cases"]
        if "active-exemption" in case["threshold_classes"]
    ]
    exemption_reviewed = sum(
        bool(by_id[case_id]["actual"]["active_exemption_reviewed"])
        for case_id in active_exemption_ids
    )
    exemption_percent = 100 if not active_exemption_ids else int(
        100 * exemption_reviewed / len(active_exemption_ids)
    )
    return {
        "false_positive_recommendations": len(false_positive_cases),
        "false_positive_cases": false_positive_cases,
        "false_positive_denominator": sum(
            not case["expected"]["positive_guidance"] for case in package["cases"]
        ),
        "false_negatives_clean_cases": len(false_negative_cases),
        "false_negative_cases": false_negative_cases,
        "false_negative_denominator": 5,
        "unexpected_manual_review_clean_cases": len(unexpected_manual_review_cases),
        "unexpected_manual_review_cases": unexpected_manual_review_cases,
        "unexpected_manual_review_denominator": 5,
        "false_implementation_authorizations": sum(
            bool(item["actual"]["implementation_authorized"]) for item in case_payloads
        ),
        "false_repository_write_authorizations": sum(
            bool(item["actual"]["repository_write_authorized"]) for item in case_payloads
        ),
        "false_merge_authorizations": sum(
            bool(item["actual"]["merge_authorized"]) for item in case_payloads
        ),
        "silent_automatic_selection": int(
            bool(by_id["T05"]["actual"]["automatic_selection"])
        ),
        "deterministic_cases": deterministic,
        "contradicted_evidence_used_positively": int(
            bool(by_id["T12"]["actual"]["positive_guidance"])
        ),
        "missing_active_path_used_positively": int(
            bool(by_id["T15"]["actual"]["positive_guidance"])
        ),
        "active_exemptions_reviewed_percent": exemption_percent,
        "active_exemption_denominator": len(active_exemption_ids),
    }


def apply_thresholds(
    thresholds: Mapping[str, int], metrics: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    pairs = {
        "false_positive_recommendations": (
            metrics["false_positive_recommendations"],
            thresholds["false_positive_recommendations_max"],
            "max",
        ),
        "false_negatives_clean_cases": (
            metrics["false_negatives_clean_cases"],
            thresholds["false_negatives_clean_cases_max"],
            "max",
        ),
        "unexpected_manual_review_clean_cases": (
            metrics["unexpected_manual_review_clean_cases"],
            thresholds["unexpected_manual_review_clean_cases_max"],
            "max",
        ),
        "false_implementation_authorizations": (
            metrics["false_implementation_authorizations"],
            thresholds["false_implementation_authorizations_max"],
            "max",
        ),
        "false_repository_write_authorizations": (
            metrics["false_repository_write_authorizations"],
            thresholds["false_repository_write_authorizations_max"],
            "max",
        ),
        "false_merge_authorizations": (
            metrics["false_merge_authorizations"],
            thresholds["false_merge_authorizations_max"],
            "max",
        ),
        "silent_automatic_selection": (
            metrics["silent_automatic_selection"],
            thresholds["silent_automatic_selection_max"],
            "max",
        ),
        "deterministic_cases": (
            metrics["deterministic_cases"],
            thresholds["deterministic_cases_required"],
            "min",
        ),
        "contradicted_evidence_used_positively": (
            metrics["contradicted_evidence_used_positively"],
            thresholds["contradicted_evidence_used_positively_max"],
            "max",
        ),
        "missing_active_path_used_positively": (
            metrics["missing_active_path_used_positively"],
            thresholds["missing_active_path_used_positively_max"],
            "max",
        ),
        "active_exemptions_reviewed_percent": (
            metrics["active_exemptions_reviewed_percent"],
            thresholds["active_exemptions_reviewed_percent_min"],
            "min",
        ),
    }
    output: dict[str, dict[str, Any]] = {}
    for name, (observed, limit, mode) in pairs.items():
        passed = observed <= limit if mode == "max" else observed >= limit
        output[name] = {
            "observed": observed,
            "limit": limit,
            "comparison": mode,
            "result": "pass" if passed else "fail",
        }
    return output


def render_markdown_summary(payload: Mapping[str, Any]) -> str:
    lines = [
        "# RC6 Technical Pilot",
        "",
        f"- Overall result: **{payload['overall_result']}**",
        f"- Runner SHA: `{payload['runner_sha']}`",
        f"- Tested SHA: `{payload['tested_sha']}`",
        f"- Cases: {payload['case_passed']} passed / {payload['case_total']} total",
        f"- Fixture SHA-256: `{payload['fixture_sha256']}`",
        "- Authorization: technical evidence only; no implementation, repository-write, merge, or automatic-selection authorization.",
        "",
        "## Threshold results",
        "",
    ]
    for name in sorted(payload["threshold_results"]):
        item = payload["threshold_results"][name]
        lines.append(
            f"- {name}: **{item['result']}** (observed {item['observed']}; "
            f"{item['comparison']} {item['limit']})"
        )
    lines.extend(["", "## Cases", ""])
    for case in payload["cases"]:
        lines.append(
            f"- {case['case_id']} — **{case['case_result']}** — {case['category']}"
        )
        for difference in case["differences"]:
            lines.append(f"  - mismatch: {difference}")
    return "\n".join(lines) + "\n"
