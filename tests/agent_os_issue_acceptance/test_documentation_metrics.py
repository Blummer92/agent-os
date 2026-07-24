from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance import documentation_metrics as metrics_module
from scripts.agent_os_issue_acceptance.documentation_metrics import (
    MAX_OUTPUT_BYTES,
    DocumentationObservation,
    build_documentation_metrics_report,
    build_documentation_observation,
    compare_documentation_observations,
    render_documentation_metrics_json,
    render_documentation_metrics_text,
)
from scripts.agent_os_issue_acceptance.issue_scanner import (
    IssueScannerRecord,
    IssueScanResult,
    IssueStateFilter,
    RetrievalFinding,
    RetrievalStatus,
)
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "agent_os_issue_acceptance" / "documentation_metrics.py"


def _body(decision: str | None, docs: tuple[str, ...] = ()) -> str:
    lines = ["```yaml", "agent_os_issue_acceptance:"]
    if decision is not None:
        lines.append(f"  documentation_impact: {decision}")
    if docs:
        lines.append("  required_docs:")
        lines.extend(f"    - {path}" for path in docs)
    lines.append("```")
    return "\n".join(lines)


def _record(
    number: int,
    decision: str | None = "docs-not-required",
    docs: tuple[str, ...] = (),
    *,
    body: str | None = None,
    revision: str | None = None,
) -> IssueScannerRecord:
    return IssueScannerRecord(
        issue_number=number,
        title=f"hostile-title-{number}",
        state="open",
        body=body if body is not None else _body(decision, docs),
        labels=("type:implementation",),
        url=f"https://example.invalid/issues/{number}",
        created_at="2026-07-24T00:00:00Z",
        updated_at="2026-07-24T01:00:00Z",
        source_revision=revision or f"rev-{number}",
    )


def _scan(
    records: tuple[IssueScannerRecord, ...],
    *,
    complete: bool = True,
    retrieved_at: str = "2026-07-24T02:00:00Z",
) -> IssueScanResult:
    return IssueScanResult(
        status=RetrievalStatus.COMPLETE if complete else RetrievalStatus.INCOMPLETE,
        records=records,
        findings=(
            (RetrievalFinding.COMPLETE,)
            if complete
            else (RetrievalFinding.API_ERROR,)
        ),
        reasons=() if complete else ("bounded source failure",),
        page_count=1,
        item_count=len(records),
        source_query="state=open",
        requested_state=IssueStateFilter.OPEN,
        retrieved_at=retrieved_at,
    )


def _report(
    number: int,
    status: Status,
    *,
    advisory: bool = False,
) -> AcceptanceReport:
    evidence = []
    if advisory:
        evidence = [
            "documentation_advisory=present",
            "ownership_verification=human-review-required",
            "semantic_relevance_verification=human-review-required",
            "authorization=advisory-only-not-readiness-write-or-merge",
        ]
    return AcceptanceReport(
        linked_issue=number,
        overall_status=status,
        checks=[CheckResult("required docs", status, "existing canonical result")],
        evidence=evidence,
    )


def _observation(
    records: tuple[IssueScannerRecord, ...],
    reports: dict[int, AcceptanceReport] | None = None,
    *,
    repository: str = "Blummer92/agent-os",
    fingerprint: str = "fingerprint-current",
    retrieved_at: str = "2026-07-24T02:00:00Z",
    complete: bool = True,
) -> DocumentationObservation:
    return build_documentation_observation(
        _scan(records, complete=complete, retrieved_at=retrieved_at),
        reports or {},
        repository=repository,
        evaluator_revision="416b828",
        window_identity="state=open",
        source_fingerprint=fingerprint,
        supported_schema_versions=("issueplan-core/v1",),
    )


def _counts(entries) -> dict[str, int]:
    return {entry.name: entry.count for entry in entries}


def test_exact_rates_zero_denominator_and_limited_observations() -> None:
    empty = build_documentation_metrics_report(_observation(())).metrics
    zero = empty.documentation_decision_coverage
    assert (zero.numerator, zero.denominator, zero.basis_points) == (0, 0, None)
    assert zero.reasons == ("denominator-empty",)

    for count in (1, 29, 30):
        records = tuple(_record(number) for number in range(1, count + 1))
        rate = build_documentation_metrics_report(
            _observation(records)
        ).metrics.documentation_decision_coverage
        assert rate.observation_count == count
        assert rate.reasons == (("limited-observations",) if count < 30 else ())


def test_exact_basis_points_use_integer_components_only() -> None:
    records = (
        _record(1, "docs-not-required"),
        _record(2, None),
        _record(3, None),
    )
    rate = build_documentation_metrics_report(
        _observation(records)
    ).metrics.documentation_decision_coverage
    assert (rate.numerator, rate.denominator, rate.basis_points) == (1, 3, 3333)


def test_decisions_remain_distinct_and_operator_review_is_count_only() -> None:
    malformed = "```yaml\nagent_os_issue_acceptance: [unterminated\n```"
    conflicting = (
        _body("docs-required") + "\n" + _body("docs-not-required")
    )
    unsupported = (
        "```yaml\nagent_os_issue_acceptance:\n"
        "  profile_version: issueplan-core/v99\n```"
    )
    records = (
        _record(1, "docs-required", ("docs/a.md",)),
        _record(2, "docs-not-required"),
        _record(3, "docs-needs-decision"),
        _record(4, None),
        _record(5, body=malformed),
        _record(6, body=conflicting),
        _record(7, body=unsupported),
    )
    observation = _observation(records)
    assert [row.decision for row in observation.records] == [
        "docs-required",
        "docs-not-required",
        "docs-needs-decision",
        "missing",
        "malformed",
        "conflicting",
        "unsupported",
    ]
    demand = _counts(
        build_documentation_metrics_report(observation).metrics.operator_review_demand_counts
    )
    assert demand["decision-review"] == 5


def test_required_docs_are_canonical_and_invalid_declarations_fail_closed() -> None:
    records = (
        _record(1, "docs-required", ("docs/z.md", "docs/a.md", "docs/a.md")),
        _record(2, "docs-required", ("bad//path",)),
    )
    observation = _observation(records)
    assert observation.records[0].required_docs == ("docs/a.md", "docs/z.md")
    assert observation.records[1].required_docs == ()
    assert "required-doc-invalid" in observation.records[1].source_reason_codes
    rate = build_documentation_metrics_report(
        observation
    ).metrics.required_documentation_declaration_coverage
    assert (rate.numerator, rate.denominator) == (1, 2)


def test_changed_file_distribution_reuses_existing_required_docs_check() -> None:
    statuses = (
        Status.PASS,
        Status.WARN,
        Status.FAIL,
        Status.MANUAL_REVIEW,
    )
    records = tuple(
        _record(number, "docs-required", (f"docs/{number}.md",))
        for number in range(1, 6)
    )
    reports = {number: _report(number, status) for number, status in enumerate(statuses, 1)}
    distribution = _counts(
        build_documentation_metrics_report(
            _observation(records, reports)
        ).metrics.changed_file_coverage_distribution
    )
    assert distribution == {
        "fail": 1,
        "manual-review": 1,
        "missing": 1,
        "pass": 1,
        "warn": 1,
    }


def test_advisory_burden_counts_bounded_markers_without_changing_status() -> None:
    report = _report(1, Status.PASS, advisory=True)
    observation = _observation(
        (_record(1, "docs-required", ("docs/a.md",)),), {1: report}
    )
    burden = _counts(
        build_documentation_metrics_report(observation).metrics.advisory_review_burden
    )
    assert burden == {"advisory-marker-count": 4, "records-with-advisory": 1}
    assert observation.records[0].coverage_status == "pass"


def test_retrieval_incompleteness_remains_visible_and_forces_complete_false() -> None:
    observation = _observation((_record(1),), complete=False)
    report = build_documentation_metrics_report(observation)
    distribution = _counts(report.metrics.retrieval_completeness_distribution)
    assert observation.complete is False
    assert report.complete is False
    assert distribution["source-inaccessible"] >= 1


def test_all_decision_and_path_drift_classifications() -> None:
    previous = _observation(
        (
            _record(1, "docs-required", ("docs/a.md",)),
            _record(2, "docs-required", ("docs/a.md",)),
            _record(3, "docs-not-required"),
            _record(5, "docs-required", ("docs/a.md", "docs/b.md")),
        ),
        fingerprint="previous",
        retrieved_at="2026-07-23T02:00:00Z",
    )
    current = _observation(
        (
            _record(1, "docs-required", ("docs/a.md",)),
            _record(2, "docs-needs-decision", ("docs/a.md", "docs/b.md")),
            _record(4, "docs-not-required"),
            _record(5, "docs-required", ("docs/b.md", "docs/c.md")),
        ),
        fingerprint="current",
    )
    drift = compare_documentation_observations(previous, current)
    decisions = _counts(drift.documentation_decision_drift)
    paths = _counts(drift.required_documentation_path_set_drift)
    assert drift.comparison_state == "comparable"
    assert decisions == {"added": 1, "changed": 1, "removed": 1, "unchanged": 2}
    assert paths == {
        "additions-only": 2,
        "mixed-change": 1,
        "removals-only": 1,
        "unchanged": 1,
    }


def test_path_order_alone_is_not_drift() -> None:
    previous = _observation(
        (_record(1, "docs-required", ("docs/b.md", "docs/a.md")),),
        fingerprint="previous",
        retrieved_at="2026-07-23T02:00:00Z",
    )
    current = _observation(
        (_record(1, "docs-required", ("docs/a.md", "docs/b.md")),),
        fingerprint="current",
    )
    drift = compare_documentation_observations(previous, current)
    assert _counts(drift.required_documentation_path_set_drift) == {"unchanged": 1}


def test_mismatched_or_incomplete_observations_are_incomparable() -> None:
    previous = _observation(
        (_record(1),), fingerprint="previous", retrieved_at="2026-07-23T02:00:00Z"
    )
    other_repo = _observation(
        (_record(1),), repository="example/other", fingerprint="current"
    )
    drift = compare_documentation_observations(previous, other_repo)
    assert drift.comparison_state == "incomparable"
    assert "repository-mismatch" in drift.reason_codes

    incomplete = _observation((_record(1),), complete=False, fingerprint="incomplete")
    drift = compare_documentation_observations(previous, incomplete)
    assert "incomplete-evidence" in drift.reason_codes


def test_equal_observation_identity_cannot_be_compared() -> None:
    observation = _observation((_record(1),))
    with pytest.raises(ValueError, match="same observation"):
        compare_documentation_observations(observation, observation)


def test_record_501_is_rejected_before_projection(monkeypatch) -> None:
    records = tuple(_record(number) for number in range(1, 502))

    def forbidden_projection(*args, **kwargs):
        raise AssertionError("projection must not run")

    monkeypatch.setattr(metrics_module, "scan_issue_metadata", forbidden_projection)
    with pytest.raises(ValueError, match="issue record limit exceeded"):
        _observation(records)


def test_canonical_json_is_utf8_deterministic_and_contains_no_floats() -> None:
    observation = _observation(
        (_record(1, "docs-required", ("docs/café.md",)),),
        {1: _report(1, Status.PASS)},
    )
    report = build_documentation_metrics_report(observation)
    first = render_documentation_metrics_json(report)
    second = render_documentation_metrics_json(report)
    assert first == second
    assert "café" in first
    payload = json.loads(first)

    def assert_no_float(value) -> None:
        if isinstance(value, dict):
            for child in value.values():
                assert_no_float(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_float(child)
        else:
            assert not isinstance(value, float)

    assert_no_float(payload)
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_canonical_encoder_rejects_float_and_invalid_surrogate() -> None:
    with pytest.raises(TypeError, match="floating-point"):
        metrics_module._encode_canonical({"value": 1.0})
    with pytest.raises(ValueError, match="Unicode surrogate"):
        metrics_module._encode_canonical({"value": "\ud800"})


def test_utf8_output_boundary_is_exact() -> None:
    exact = {"x": "a" * (MAX_OUTPUT_BYTES - 9)}
    assert len(metrics_module._encode_canonical(exact)) == MAX_OUTPUT_BYTES
    too_large = {"x": "a" * (MAX_OUTPUT_BYTES - 8)}
    with pytest.raises(ValueError, match="65536 UTF-8 bytes"):
        metrics_module._encode_canonical(too_large)


def test_hostile_source_text_does_not_leak_or_mutate_inputs() -> None:
    secret = "TOP-SECRET-CALLER-BODY"
    record = replace(
        _record(1, body=_body("docs-required", ("docs/a.md",)) + secret),
        title="TOP-SECRET-TITLE",
        url="https://secret.invalid/value",
    )
    report = _report(1, Status.PASS, advisory=True)
    before_checks = list(report.checks)
    before_evidence = list(report.evidence)
    rendered = render_documentation_metrics_json(
        build_documentation_metrics_report(_observation((record,), {1: report}))
    )
    assert secret not in rendered
    assert "TOP-SECRET-TITLE" not in rendered
    assert "secret.invalid" not in rendered
    assert report.checks == before_checks
    assert report.evidence == before_evidence


def test_text_output_is_bounded_non_authoritative_and_disclaims_semantics() -> None:
    text = render_documentation_metrics_text(
        build_documentation_metrics_report(_observation((_record(1),)))
    )
    assert len(text.encode("utf-8")) <= MAX_OUTPUT_BYTES
    assert "execution_authorized: false" in text
    assert "side_effects_performed: false" in text
    assert "does not prove semantic correctness" in text
    for conclusion in ("healthy", "unhealthy", "improved", "regressed", "leaderboard"):
        assert conclusion not in text


def test_payload_has_no_composite_or_governance_decision_fields() -> None:
    payload = json.loads(
        render_documentation_metrics_json(
            build_documentation_metrics_report(_observation((_record(1),)))
        )
    )
    forbidden = {
        "score",
        "grade",
        "ranking",
        "leaderboard",
        "readiness",
        "approval",
        "merge_eligibility",
        "enforcement",
        "ownership_decision",
        "assignment",
        "migration",
    }

    def collect_keys(value) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(collect_keys(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(collect_keys(child) for child in value)) if value else set()
        return set()

    assert collect_keys(payload).isdisjoint(forbidden)


def test_module_has_no_forbidden_io_or_runtime_imports() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    assert imports.isdisjoint(
        {"os", "pathlib", "requests", "socket", "subprocess", "time", "datetime"}
    )
    assert calls.isdisjoint(
        {"open", "system", "popen", "run", "check_call", "check_output", "getenv"}
    )
