from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import Status

from .checker import evaluate_issue_labels
from .issue_metadata import load_issue_form_fields, parse_issue_form_body
from .label_map import expected_labels, load_label_map

_OWNER_PREFIX = "owner:"
_SAFE_BASE_LABELS = {"agent-os"}


@dataclass(frozen=True)
class LabelApplicationPlan:
    outcome: Status
    expected_labels: tuple[str, ...]
    existing_labels: tuple[str, ...]
    candidate_additions: tuple[str, ...]
    approved_additions: tuple[str, ...]
    already_present: tuple[str, ...]
    skipped_by_policy: tuple[str, ...]
    conflicting_labels: tuple[str, ...]
    unknown_values: tuple[str, ...]
    unavailable_labels: tuple[str, ...]
    manual_review_reasons: tuple[str, ...]


def plan_label_application(
    issue_body: str,
    existing_labels: list[str],
    available_labels: list[str],
    issue_form_path: str | Path,
    label_map_path: str | Path,
) -> LabelApplicationPlan:
    existing = _normalized_set(existing_labels)
    available = _normalized_set(available_labels)
    label_map = load_label_map(label_map_path)
    fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(issue_body, fields)
    expected, unknown_values = expected_labels(metadata, label_map)
    checker_report = evaluate_issue_labels(
        issue_body=issue_body,
        existing_labels=sorted(existing),
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )

    reasons = list(checker_report.manual_review_items)
    for check in checker_report.checks:
        if check.status in {Status.MANUAL_REVIEW, Status.FAIL}:
            reasons.append(f"{check.name}: {check.message}")
            reasons.extend(check.evidence)

    candidate_additions: set[str] = set()
    already_present = expected & existing
    unavailable: set[str] = set()
    conflicts: set[str] = set()

    for label in sorted(_SAFE_BASE_LABELS & expected):
        _consider_safe_label(
            label,
            existing=existing,
            available=available,
            candidate_additions=candidate_additions,
            unavailable=unavailable,
            reasons=reasons,
        )

    desired_owner = _desired_owner_label(metadata, label_map.fields, reasons)
    existing_owners = {label for label in existing if label.startswith(_OWNER_PREFIX)}
    if desired_owner:
        other_owners = existing_owners - {desired_owner}
        if other_owners:
            conflicts.update(existing_owners)
            conflicts.add(desired_owner)
            reasons.append(
                "owner label conflict: existing owner labels must be reviewed before another owner label is proposed"
            )
        elif desired_owner in existing:
            already_present.add(desired_owner)
        else:
            _consider_safe_label(
                desired_owner,
                existing=existing,
                available=available,
                candidate_additions=candidate_additions,
                unavailable=unavailable,
                reasons=reasons,
            )

    safe_policy_labels = set(_SAFE_BASE_LABELS)
    if desired_owner:
        safe_policy_labels.add(desired_owner)
    skipped = expected - safe_policy_labels

    for value in unknown_values:
        reasons.append(f"unmapped value requires review: {value}")

    unique_reasons = tuple(sorted(set(reasons)))
    requires_review = bool(unique_reasons or unavailable or conflicts or unknown_values)
    outcome = Status.MANUAL_REVIEW if requires_review else Status.PASS
    approved = () if requires_review else tuple(sorted(candidate_additions))

    return LabelApplicationPlan(
        outcome=outcome,
        expected_labels=tuple(sorted(expected)),
        existing_labels=tuple(sorted(existing)),
        candidate_additions=tuple(sorted(candidate_additions)),
        approved_additions=approved,
        already_present=tuple(sorted(already_present)),
        skipped_by_policy=tuple(sorted(skipped)),
        conflicting_labels=tuple(sorted(conflicts)),
        unknown_values=tuple(sorted(set(unknown_values))),
        unavailable_labels=tuple(sorted(unavailable)),
        manual_review_reasons=unique_reasons,
    )


def application_plan_to_dict(plan: LabelApplicationPlan) -> dict[str, object]:
    return {
        "outcome": plan.outcome.value,
        "expected_labels": list(plan.expected_labels),
        "existing_labels": list(plan.existing_labels),
        "candidate_additions": list(plan.candidate_additions),
        "approved_additions": list(plan.approved_additions),
        "already_present": list(plan.already_present),
        "skipped_by_policy": list(plan.skipped_by_policy),
        "conflicting_labels": list(plan.conflicting_labels),
        "unknown_values": list(plan.unknown_values),
        "unavailable_labels": list(plan.unavailable_labels),
        "manual_review_reasons": list(plan.manual_review_reasons),
    }


def render_application_plan(
    plan: LabelApplicationPlan,
    *,
    issue_number: int,
    event_type: str,
    commit_sha: str,
    exit_status: int = 0,
) -> str:
    lines = [
        "Issue Label Application Dry Run",
        f"Issue number: #{issue_number}",
        f"Event type: {event_type}",
        f"Tested commit SHA: {commit_sha}",
        f"Outcome: {plan.outcome.value}",
        "Expected labels:",
        *_bullets(plan.expected_labels),
        "Existing labels:",
        *_bullets(plan.existing_labels),
        "Candidate additions:",
        *_bullets(plan.candidate_additions),
        "Approved additions:",
        *_bullets(plan.approved_additions),
        "Already present:",
        *_bullets(plan.already_present),
        "Skipped by policy:",
        *_bullets(plan.skipped_by_policy),
        "Conflicting labels:",
        *_bullets(plan.conflicting_labels),
        "Unknown values:",
        *_bullets(plan.unknown_values),
        "Unavailable labels:",
        *_bullets(plan.unavailable_labels),
        "Manual review reasons:",
        *_bullets(plan.manual_review_reasons),
        f"Exit status: {exit_status}",
    ]
    return "\n".join(lines) + "\n"


def _consider_safe_label(
    label: str,
    *,
    existing: set[str],
    available: set[str],
    candidate_additions: set[str],
    unavailable: set[str],
    reasons: list[str],
) -> None:
    if label in existing:
        return
    if label not in available:
        unavailable.add(label)
        reasons.append(f"repository label is unavailable: {label}")
        return
    candidate_additions.add(label)


def _desired_owner_label(
    metadata: dict[str, list[str]],
    fields: dict[str, object],
    reasons: list[str],
) -> str | None:
    values = metadata.get("owner", [])
    if len(values) != 1:
        reasons.append("owner metadata must contain exactly one value")
        return None

    mapping = ((fields.get("owner") or {}).get("values", {}))  # type: ignore[union-attr]
    mapped = mapping.get(values[0])
    labels = [] if not mapped else [str(label) for label in mapped.get("labels", [])]
    owner_labels = [label for label in labels if label.startswith(_OWNER_PREFIX)]
    if len(owner_labels) != 1:
        reasons.append("owner metadata must map to exactly one owner label")
        return None
    return owner_labels[0]


def _normalized_set(values: list[str]) -> set[str]:
    return {value.strip() for value in values if value and value.strip()}


def _bullets(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]
