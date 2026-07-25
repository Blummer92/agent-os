from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

import yaml

from scripts.agent_os_issue_acceptance.models import AcceptanceReport, CheckResult, Status
from scripts.agent_os_issue_acceptance.report import render_report

from .draft import IssueDraftInput, IssueDraftResult, draft_result_to_dict, render_draft_preview
from .issue_metadata import (
    IssueFormField,
    IssueFormSchema,
    canonical_field_id,
    load_issue_form_schema,
    parse_issue_form_body,
)
from .report import report_to_dict


class DraftReasonCode(str, Enum):
    ELIGIBLE_VALID = "eligible-valid"
    ELIGIBLE_WARNING = "eligible-warning"
    MISSING_REQUIRED_EVIDENCE = "missing-required-evidence"
    MALFORMED_STRUCTURED_INPUT = "malformed-structured-input"
    UNKNOWN_OR_UNSUPPORTED_VALUE = "unknown-or-unsupported-value"
    DUPLICATE_CANONICAL_FIELD = "duplicate-raw-or-canonical-field"
    UNAVAILABLE_LABEL = "unavailable-label"
    CONFLICTING_OWNER = "conflicting-owner-evidence"
    UNSAFE_EXTERNAL_WRITE = "unsafe-external-write-request"
    PARSER_ROUND_TRIP_AMBIGUITY = "parser-round-trip-ambiguity"
    ISSUE_FORM_SCHEMA_DRIFT = "unsupported-or-drifted-issue-form-schema"
    DUPLICATE_CANDIDATE_ADVISORY = "duplicate-local-candidate-advisory"


_REASON_ORDER = tuple(DraftReasonCode)
_HARD = {
    DraftReasonCode.MALFORMED_STRUCTURED_INPUT,
    DraftReasonCode.UNSAFE_EXTERNAL_WRITE,
}
_REVIEW = {
    DraftReasonCode.MISSING_REQUIRED_EVIDENCE,
    DraftReasonCode.UNKNOWN_OR_UNSUPPORTED_VALUE,
    DraftReasonCode.DUPLICATE_CANONICAL_FIELD,
    DraftReasonCode.UNAVAILABLE_LABEL,
    DraftReasonCode.CONFLICTING_OWNER,
    DraftReasonCode.PARSER_ROUND_TRIP_AMBIGUITY,
    DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT,
}
_FORMAT_INVALID = {
    DraftReasonCode.MALFORMED_STRUCTURED_INPUT,
    DraftReasonCode.PARSER_ROUND_TRIP_AMBIGUITY,
    DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT,
}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOP_LEVEL_KEYS = {
    "name",
    "description",
    "title",
    "labels",
    "assignees",
    "type",
    "projects",
    "body",
}
_ELEMENT_KEYS = {"type", "id", "attributes", "validations"}
_BASE_ATTRIBUTES = {"label", "description", "placeholder"}
_SUPPORTED_ATTRIBUTES = {
    "markdown": {"value"},
    "input": _BASE_ATTRIBUTES,
    "textarea": _BASE_ATTRIBUTES,
    "dropdown": {"label", "description", "multiple", "options", "default"},
    "checkboxes": {"label", "description", "options"},
}
_BEHAVIORAL_ATTRIBUTES = {
    "input": {"value"},
    "textarea": {"value", "render"},
    "dropdown": {"default"},
}


class DraftExitCode(IntEnum):
    ELIGIBLE_SUCCESS = 0
    ELIGIBLE_WARNING = 10
    MANUAL_REVIEW = 20
    VALIDATION_FAILURE = 30
    INVALID_INPUT_OR_USAGE = 64


@dataclass(frozen=True)
class IssueDraftValidationResult:
    draft: IssueDraftResult
    status: Status
    reason_codes: tuple[DraftReasonCode, ...]
    format_valid: bool
    submission_eligible: bool
    parser_ambiguity_evidence: tuple[str, ...]
    schema_drift_evidence: tuple[str, ...]
    duplicate_candidate_evidence: tuple[str, ...]
    evidence: tuple[str, ...]
    report: AcceptanceReport
    write_authorized: bool = False
    mutation_performed: bool = False


def validate_issue_draft(
    draft: IssueDraftResult,
    source_input: IssueDraftInput,
    issue_form_path: str | Path,
    *,
    available_labels: Iterable[str] | None = None,
    local_issue_summaries: Sequence[str] = (),
) -> IssueDraftValidationResult:
    schema = load_issue_form_schema(issue_form_path)
    parser_evidence = _parser_evidence(draft, source_input, schema)
    schema_evidence = _schema_evidence(issue_form_path, schema)
    duplicate_evidence = _duplicate_evidence(draft.title, local_issue_summaries)

    reasons = set(_draft_reason_codes(draft, source_input))
    if parser_evidence:
        reasons.add(DraftReasonCode.PARSER_ROUND_TRIP_AMBIGUITY)
    if schema_evidence:
        reasons.add(DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT)
    if duplicate_evidence:
        reasons.add(DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY)

    source_values = _source_values(source_input)
    owner_values = source_values.get("owner", ())
    if owner_values and len(owner_values) != 1:
        reasons.add(DraftReasonCode.CONFLICTING_OWNER)
    external_values = source_values.get("external-write", ())
    if external_values and any(value != "no-external-write" for value in external_values):
        reasons.add(DraftReasonCode.UNSAFE_EXTERNAL_WRITE)

    unavailable = _unavailable_labels(draft.proposed_labels, available_labels)
    if unavailable:
        reasons.add(DraftReasonCode.UNAVAILABLE_LABEL)

    status = _status(draft.report.overall_status, reasons)
    if status == Status.PASS:
        reasons.add(DraftReasonCode.ELIGIBLE_VALID)
    elif status == Status.WARN:
        reasons.add(DraftReasonCode.ELIGIBLE_WARNING)
    ordered = tuple(code for code in _REASON_ORDER if code in reasons)
    format_valid = not bool(reasons & _FORMAT_INVALID)
    eligible = status in {Status.PASS, Status.WARN}
    evidence = tuple(
        [
            f"reason codes: {', '.join(code.value for code in ordered)}",
            f"format_valid={str(format_valid).lower()}",
            f"submission_eligible={str(eligible).lower()}",
            "write_authorized=false",
            "mutation_performed=false",
        ]
        + [f"unavailable label: {label}" for label in unavailable]
    )
    report = _report(
        draft,
        status,
        ordered,
        parser_evidence,
        schema_evidence,
        duplicate_evidence,
        evidence,
    )
    return IssueDraftValidationResult(
        draft=draft,
        status=status,
        reason_codes=ordered,
        format_valid=format_valid,
        submission_eligible=eligible,
        parser_ambiguity_evidence=parser_evidence,
        schema_drift_evidence=schema_evidence,
        duplicate_candidate_evidence=duplicate_evidence,
        evidence=evidence,
        report=report,
    )


def validation_result_to_dict(result: IssueDraftValidationResult) -> dict[str, object]:
    payload = draft_result_to_dict(result.draft)
    payload["draft_report"] = payload.pop("report")
    payload.update(
        validation_status=result.status.value,
        reason_codes=[code.value for code in result.reason_codes],
        format_valid=result.format_valid,
        submission_eligible=result.submission_eligible,
        write_authorized=result.write_authorized,
        mutation_performed=result.mutation_performed,
        parser_ambiguity_evidence=list(result.parser_ambiguity_evidence),
        schema_drift_evidence=list(result.schema_drift_evidence),
        duplicate_candidate_evidence=list(result.duplicate_candidate_evidence),
        validation_evidence=list(result.evidence),
        report=report_to_dict(result.report),
    )
    return payload


def render_validation_preview(result: IssueDraftValidationResult) -> str:
    lines = [
        "Agent OS Issue Draft Validation",
        f"Validation status: {result.status.value}",
        f"Reason codes: {', '.join(code.value for code in result.reason_codes)}",
        f"Format valid: {_yes_no(result.format_valid)}",
        f"Submission eligible: {_yes_no(result.submission_eligible)}",
        f"Write authorized: {_yes_no(result.write_authorized)}",
        f"Mutation performed: {_yes_no(result.mutation_performed)}",
        "Parser ambiguity evidence:",
        *_bullets(result.parser_ambiguity_evidence),
        "Schema drift evidence:",
        *_bullets(result.schema_drift_evidence),
        "Duplicate candidate evidence (advisory):",
        *_bullets(result.duplicate_candidate_evidence),
        "Draft preview:",
        render_draft_preview(result.draft).rstrip("\n"),
        "Normalized validation report:",
        render_report(result.report).rstrip("\n"),
    ]
    return "\n".join(lines) + "\n"


def validation_exit_code(result: IssueDraftValidationResult) -> int:
    return int(
        DraftExitCode.ELIGIBLE_SUCCESS
        if result.status == Status.PASS
        else DraftExitCode.ELIGIBLE_WARNING
        if result.status == Status.WARN
        else DraftExitCode.MANUAL_REVIEW
        if result.status == Status.MANUAL_REVIEW
        else DraftExitCode.VALIDATION_FAILURE
    )


def _draft_reason_codes(
    draft: IssueDraftResult, source_input: IssueDraftInput
) -> tuple[DraftReasonCode, ...]:
    codes: set[DraftReasonCode] = set()
    if source_input.input_issues:
        codes.add(DraftReasonCode.MALFORMED_STRUCTURED_INPUT)
    for reason in draft.manual_review_reasons:
        text = reason.casefold()
        if (
            "required field is missing" in text
            or "required checkbox" in text
            or "title is required" in text
        ):
            codes.add(DraftReasonCode.MISSING_REQUIRED_EVIDENCE)
        elif (
            "must be a string" in text
            or "must be a mapping" in text
            or "unknown top-level" in text
        ):
            codes.add(DraftReasonCode.MALFORMED_STRUCTURED_INPUT)
        elif "multiple input fields map" in text or "duplicate canonical field" in text:
            codes.add(DraftReasonCode.DUPLICATE_CANONICAL_FIELD)
        elif "repository label is unavailable" in text:
            codes.add(DraftReasonCode.UNAVAILABLE_LABEL)
        elif "owner" in text and any(
            word in text for word in ("multiple", "exactly one", "conflict")
        ):
            codes.add(DraftReasonCode.CONFLICTING_OWNER)
        elif "external-write" in text and any(
            word in text for word in ("request", "unsafe")
        ):
            codes.add(DraftReasonCode.UNSAFE_EXTERNAL_WRITE)
        elif "unsupported control" in text or "malformed attributes or validations" in text:
            codes.add(DraftReasonCode.ISSUE_FORM_SCHEMA_DRIFT)
        else:
            codes.add(DraftReasonCode.UNKNOWN_OR_UNSUPPORTED_VALUE)
    if draft.report.overall_status == Status.FAIL:
        codes.add(DraftReasonCode.MALFORMED_STRUCTURED_INPUT)
    return tuple(code for code in _REASON_ORDER if code in codes)


def _status(draft_status: Status, reasons: set[DraftReasonCode]) -> Status:
    if draft_status == Status.FAIL or reasons & _HARD:
        return Status.FAIL
    if draft_status == Status.MANUAL_REVIEW or reasons & _REVIEW:
        return Status.MANUAL_REVIEW
    if draft_status == Status.WARN or DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY in reasons:
        return Status.WARN
    return Status.PASS


def _source_values(source_input: IssueDraftInput) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for raw_key, values in source_input.fields:
        grouped[canonical_field_id(raw_key)].extend(values)
    return {key: tuple(values) for key, values in grouped.items()}


def _parser_evidence(
    draft: IssueDraftResult,
    source_input: IssueDraftInput,
    schema: IssueFormSchema,
) -> tuple[str, ...]:
    evidence: list[str] = []
    fields = {field.canonical_id: field.label for field in schema.fields}
    labels = {field.label.casefold(): field.canonical_id for field in schema.fields}
    for raw_key, values in source_input.fields:
        for value in values:
            for line in value.splitlines():
                match = re.match(r"^###\s+(.+?)\s*$", line)
                if match and match.group(1).casefold() in labels:
                    evidence.append(
                        f"field {raw_key} contains canonical-looking heading: {match.group(1)}"
                    )

    heading_counts = Counter(
        line[4:].strip() for line in draft.body.splitlines() if line.startswith("### ")
    )
    for field in schema.fields:
        count = heading_counts.get(field.label, 0)
        if count != 1:
            evidence.append(
                f"rendered heading count for {field.canonical_id} is {count}, expected 1"
            )

    parsed = parse_issue_form_body(draft.body, fields)
    expected = _source_values(source_input)
    schema_by_id = {field.canonical_id: field for field in schema.fields}
    expected_keys = {
        key for key, values in expected.items() if values and key in schema_by_id
    }
    parsed_keys = set(parsed)
    for key in sorted(expected_keys - parsed_keys):
        evidence.append(f"rendered body did not round-trip expected field: {key}")
    for key in sorted(parsed_keys - expected_keys):
        if schema_by_id[key].control_type != "checkboxes":
            evidence.append(f"rendered body produced unexpected parsed field: {key}")
    for key in sorted(expected_keys & parsed_keys):
        field = schema_by_id[key]
        if field.control_type == "checkboxes":
            continue
        if _expected_values(field, expected[key]) != tuple(parsed[key]):
            evidence.append(f"round-trip values changed for {key}")
    return tuple(sorted(set(evidence)))


def _expected_values(field: IssueFormField, values: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        return ()
    content = values[0] if len(values) == 1 else "\n".join(f"- {value}" for value in values)
    parsed = parse_issue_form_body(
        f"### {field.label}\n\n{content}\n",
        {field.canonical_id: field.label},
    )
    return tuple(parsed.get(field.canonical_id, ()))


def _schema_evidence(
    issue_form_path: str | Path, schema: IssueFormSchema
) -> tuple[str, ...]:
    evidence = list(schema.unsupported_controls)
    raw = yaml.safe_load(Path(issue_form_path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        return ("issue form root is not a mapping",)

    evidence.extend(
        f"unsupported top-level issue-form key: {key}"
        for key in sorted(set(raw) - _TOP_LEVEL_KEYS)
    )
    evidence.extend(_top_level_type_evidence(raw))
    body = raw.get("body", [])
    if not isinstance(body, list):
        return tuple(sorted(set([*evidence, "issue form body is not a list"])))

    raw_ids: list[str] = []
    canonical_ids: list[str] = []
    labels: list[str] = []
    non_markdown_fields = 0
    for index, item in enumerate(body):
        if not isinstance(item, Mapping):
            evidence.append(f"body[{index}] is not a mapping")
            continue
        evidence.extend(
            f"body[{index}] has unsupported element key: {key}"
            for key in sorted(set(item) - _ELEMENT_KEYS)
        )
        control = item.get("type")
        if not isinstance(control, str) or not control:
            evidence.append(f"body[{index}] type must be a non-empty string")
            continue
        attrs = item.get("attributes") or {}
        validations = item.get("validations") or {}
        if not isinstance(attrs, Mapping) or not isinstance(validations, Mapping):
            evidence.append(f"body[{index}] has malformed attributes or validations")
            continue

        evidence.extend(_attribute_evidence(index, control, attrs))
        evidence.extend(_validation_evidence(index, item.get("id"), validations))
        if control == "markdown":
            continue
        non_markdown_fields += 1

        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            evidence.append(f"body[{index}] input control must define a string id")
        else:
            raw_ids.append(raw_id)
            canonical_ids.append(canonical_field_id(raw_id))
            if not _ID_RE.fullmatch(raw_id):
                evidence.append(f"body[{index}] field id is invalid: {raw_id}")

        label = attrs.get("label")
        if not isinstance(label, str) or not label.strip():
            evidence.append(f"body[{index}] label must be a non-empty string")
        else:
            labels.append(label)

        if control in {"dropdown", "checkboxes"}:
            evidence.extend(_option_evidence(index, control, attrs.get("options")))

    if not non_markdown_fields:
        evidence.append("issue form body contains no input fields")
    evidence.extend(
        f"duplicate raw field id: {value}" for value in _duplicates(raw_ids)
    )
    evidence.extend(
        f"duplicate canonical field id: {value}"
        for value in _duplicates(canonical_ids)
    )
    evidence.extend(
        f"duplicate field label: {value}" for value in _duplicates(labels)
    )
    return tuple(sorted(set(evidence)))


def _top_level_type_evidence(raw: Mapping[object, object]) -> list[str]:
    evidence: list[str] = []
    for key in ("name", "description"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            evidence.append(f"top-level {key} must be a non-empty string")
    for key in ("title", "type"):
        if key in raw and not isinstance(raw[key], str):
            evidence.append(f"top-level {key} must be a string")
    for key in ("labels", "assignees", "projects"):
        if key in raw and not _string_or_string_list(raw[key]):
            evidence.append(f"top-level {key} must be a string or string list")
    return evidence


def _string_or_string_list(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _attribute_evidence(
    index: int, control: str, attrs: Mapping[object, object]
) -> list[str]:
    field_name = attrs.get("label", "<none>")
    allowed = _SUPPORTED_ATTRIBUTES.get(control, set())
    known_behavioral = _BEHAVIORAL_ATTRIBUTES.get(control, set())
    evidence = [
        f"body[{index}] field {field_name} has unsupported attribute: {key}"
        for key in sorted(set(attrs) - allowed - known_behavioral)
    ]
    evidence.extend(
        f"body[{index}] field {field_name} uses unsupported renderer behavior: {key}"
        for key in sorted(set(attrs) & known_behavioral)
    )
    for key in ("label", "description", "placeholder"):
        if key in attrs and not isinstance(attrs[key], str):
            evidence.append(f"body[{index}] attribute {key} must be a string")
    if control == "markdown" and not isinstance(attrs.get("value"), str):
        evidence.append(f"body[{index}] markdown value must be a string")
    if control == "dropdown" and "multiple" in attrs:
        if not isinstance(attrs["multiple"], bool):
            evidence.append(f"body[{index}] dropdown multiple must be boolean")
        elif attrs["multiple"] is True:
            evidence.append(
                f"body[{index}] dropdown multiple selection is unsupported by local renderer"
            )
    return evidence


def _validation_evidence(
    index: int, field_id: object, validations: Mapping[object, object]
) -> list[str]:
    evidence = [
        f"body[{index}] field {field_id or '<none>'} has unsupported validation: {key}"
        for key in sorted(set(validations) - {"required"})
    ]
    if "required" in validations and not isinstance(validations["required"], bool):
        evidence.append(
            f"body[{index}] field {field_id or '<none>'} has non-boolean required validation"
        )
    return evidence


def _option_evidence(index: int, control: str, options: object) -> list[str]:
    if not isinstance(options, list) or not options:
        return [f"body[{index}] options must be a non-empty list"]
    evidence: list[str] = []
    normalized: list[str] = []
    for option_index, option in enumerate(options):
        if control == "checkboxes":
            if not isinstance(option, Mapping):
                evidence.append(
                    f"body[{index}] checkbox option {option_index} is malformed"
                )
                continue
            evidence.extend(
                f"body[{index}] checkbox option {option_index} has unsupported key: {key}"
                for key in sorted(set(option) - {"label", "required"})
            )
            label = option.get("label")
            if not isinstance(label, str) or not label.strip():
                evidence.append(
                    f"body[{index}] checkbox option {option_index} label is invalid"
                )
                continue
            if "required" in option and not isinstance(option["required"], bool):
                evidence.append(
                    f"body[{index}] checkbox option {option_index} required must be boolean"
                )
            normalized.append(label)
            continue

        if not isinstance(option, str) or not option.strip():
            evidence.append(f"body[{index}] dropdown option {option_index} is invalid")
            continue
        if option.casefold() == "none":
            evidence.append(f"body[{index}] dropdown option uses reserved value: {option}")
        normalized.append(option)

    evidence.extend(
        f"body[{index}] has duplicate option: {value}"
        for value in _duplicates(normalized)
    )
    return evidence


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    counts = Counter(values)
    return tuple(sorted(value for value, count in counts.items() if count > 1))


def _duplicate_evidence(title: str, summaries: Sequence[str]) -> tuple[str, ...]:
    normalized = _normalize_candidate(title)
    return tuple(
        sorted(
            {
                f"local candidate matches prepared title: {summary}"
                for summary in summaries
                if _normalize_candidate(summary) == normalized
            }
        )
    )


def _normalize_candidate(value: str) -> str:
    value = re.sub(r"^\[agent os\]\s*", "", value.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value.casefold())


def _unavailable_labels(
    proposed: Sequence[str], available: Iterable[str] | None
) -> tuple[str, ...]:
    if available is None:
        return ()
    available_set = {label.strip() for label in available if label.strip()}
    return tuple(sorted(label for label in proposed if label not in available_set))


def _report(
    draft: IssueDraftResult,
    status: Status,
    codes: tuple[DraftReasonCode, ...],
    parser_evidence: tuple[str, ...],
    schema_evidence: tuple[str, ...],
    duplicate_evidence: tuple[str, ...],
    evidence: tuple[str, ...],
) -> AcceptanceReport:
    checks = [
        *draft.report.checks,
        _check("parser round-trip", parser_evidence, Status.MANUAL_REVIEW),
        _check("issue-form schema drift", schema_evidence, Status.MANUAL_REVIEW),
        _check("duplicate candidates", duplicate_evidence, Status.WARN),
        CheckResult(
            "submission eligibility",
            status,
            "offline validation is deterministic and fail-closed",
            list(evidence),
        ),
        CheckResult(
            "authorization boundary",
            Status.PASS,
            "validation grants no write authorization and performs no mutation",
            ["write_authorized=false", "mutation_performed=false"],
        ),
    ]
    manual = list(draft.report.manual_review_items)
    if status == Status.MANUAL_REVIEW:
        manual.extend(code.value for code in codes)
    blockers = list(draft.report.blockers)
    if status == Status.FAIL:
        blockers.append("Offline issue-draft validation failed closed.")
    return AcceptanceReport(
        linked_issue=draft.report.linked_issue,
        overall_status=status,
        checks=checks,
        linked_issue_result=draft.report.linked_issue_result,
        manual_review_items=list(dict.fromkeys(manual)),
        evidence=list(dict.fromkeys([*draft.report.evidence, *evidence])),
        blockers=list(dict.fromkeys(blockers)),
        remaining_risks=list(
            dict.fromkeys(
                [
                    *draft.report.remaining_risks,
                    "Submission eligibility does not imply readiness, approval, authentication, or write authorization.",
                    "Live GitHub submission remains outside #601 and blocked on #602 authorization.",
                ]
            )
        ),
        informational_checks=draft.report.informational_checks,
    )


def _check(name: str, evidence: tuple[str, ...], nonpass: Status) -> CheckResult:
    if evidence:
        return CheckResult(name, nonpass, f"{name} requires review", list(evidence))
    return CheckResult(name, Status.PASS, f"{name} evidence is clear")


def _bullets(values: tuple[str, ...]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- none"]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
