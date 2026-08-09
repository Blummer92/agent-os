"""Read-only end-to-end CLI for deterministic PR review remediation evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .coordination import coordinate_resolution, serialize_resolution_plan
from .models import AUTHORITY_FIELDS, EvidenceValidationError, canonical_json
from .normalization import normalize_pr_snapshot, normalize_review_threads
from .planning import plan_remediation
from .preflight import PreflightResult, preflight

MAX_INPUT_CHARS = 2_000_000
_REQUIRED_FIELDS = {
    "snapshot",
    "review_threads",
    "expected_head",
    "allowed_files",
    "draft_allowed",
    "candidates",
    "changed_files",
    "finding_fixes",
    "validation_evidence",
    "current_head_sha",
    "final_captured_head_sha",
}
_OPTIONAL_FIELDS = {"failure_evidence", "repair_handoff"}


def _input_envelope(payload: Any) -> dict[str, Any]:
    if type(payload) is not dict:
        raise EvidenceValidationError("input envelope must be exactly dict")
    if any(type(key) is not str for key in payload):
        raise EvidenceValidationError("input envelope keys must be strings")
    missing = _REQUIRED_FIELDS - set(payload)
    unknown = set(payload) - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if missing:
        raise EvidenceValidationError(
            "missing input fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise EvidenceValidationError(
            "unknown input fields: " + ", ".join(sorted(unknown))
        )
    if len(canonical_json(payload)) > MAX_INPUT_CHARS:
        raise EvidenceValidationError("input envelope exceeds size limit")
    return payload


def _preflight_to_dict(result: PreflightResult) -> dict[str, Any]:
    return {
        "overall_status": result.overall_status.value,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": list(check.evidence),
            }
            for check in result.checks
        ],
        "expected_head": result.expected_head,
        "allowed_files": list(result.allowed_files),
        "outside_allowed_files": list(result.outside_allowed_files),
        "duplicate_thread_ids": list(result.duplicate_thread_ids),
        "duplicate_comment_ids": list(result.duplicate_comment_ids),
        "manual_review_items": list(result.manual_review_items),
        "execution_authorized": result.execution_authorized,
        "external_write_authorized": result.external_write_authorized,
        "merge_authorized": result.merge_authorized,
        "side_effects_performed": result.side_effects_performed,
    }


def evaluate(payload: Any) -> dict[str, Any]:
    """Compose PRR1-3 from supplied local evidence without performing side effects."""

    data = _input_envelope(payload)
    snapshot = normalize_pr_snapshot(data["snapshot"])
    review_threads = normalize_review_threads(data["review_threads"])
    preflight_result = preflight(
        snapshot,
        expected_head=data["expected_head"],
        allowed_files=data["allowed_files"],
        review_threads=review_threads,
        draft_allowed=data["draft_allowed"],
    )
    remediation_plan = plan_remediation(
        snapshot,
        review_threads,
        data["candidates"],
        data["allowed_files"],
        failure_evidence=data.get("failure_evidence"),
        repair_handoff=data.get("repair_handoff"),
    )
    resolution_plan = coordinate_resolution(
        snapshot,
        review_threads,
        preflight_result,
        remediation_plan,
        data["changed_files"],
        data["finding_fixes"],
        data["validation_evidence"],
        current_head_sha=data["current_head_sha"],
        final_captured_head_sha=data["final_captured_head_sha"],
    )
    report = {
        "contract_version": "agent-os-pr-remediation-cli/v1",
        "preflight": _preflight_to_dict(preflight_result),
        "remediation_plan": remediation_plan.to_dict(),
        "resolution_plan": serialize_resolution_plan(resolution_plan),
        **{field: False for field in AUTHORITY_FIELDS},
    }
    canonical_json(report)
    return report


def render_text(report: dict[str, Any]) -> str:
    """Render a concise operator summary from the canonical report envelope."""

    preflight_result = report["preflight"]
    remediation = report["remediation_plan"]
    resolution = report["resolution_plan"]
    lines = [
        "Agent OS PR remediation evaluation",
        f"preflight: {preflight_result['overall_status']}",
        f"findings: {len(remediation['findings'])}",
        f"tasks: {len(remediation['tasks'])}",
        f"threads: {len(resolution['thread_results'])}",
    ]
    for thread in resolution["thread_results"]:
        lines.append(
            "thread "
            f"{thread['thread_id']}: {thread['validation_state']} -> "
            f"{thread['suggested_action']} (eligible={str(thread['resolution_eligible']).lower()})"
        )
    lines.append(
        "authority: execution=false external-write=false merge=false side-effects=false"
    )
    return "\n".join(lines) + "\n"


def _read_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate local PR review-remediation evidence without performing writes."
    )
    parser.add_argument("--input", required=True, help="Path to the bounded PRR1-3 evidence JSON file.")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)

    try:
        report = evaluate(_read_json(args.input))
    except (OSError, json.JSONDecodeError, EvidenceValidationError, KeyError, TypeError, ValueError) as error:
        print(f"error: invalid remediation evidence: {error}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(canonical_json(report))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
