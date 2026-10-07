from __future__ import annotations

import pytest

from instructional_workflow_contracts.request_interpretation import (
    RequestInterpretation,
    validate_request_interpretation,
)
from instructional_workflow_contracts.common import ValidationStatus

from agent_os_execution_service.cohort_admission import (
    CohortAdmissionStatus,
    admit_request_cohort,
)
from scripts.agent_os_candidate_packet.executable_lane_selection import MAX_CANDIDATES


REPOSITORY = "Blummer92/agent-os"
SOURCE_QUERY = "repo=Blummer92/agent-os state=open"


def request(
    *,
    kind: str,
    resource_id: str | None,
    repository: str = REPOSITORY,
    constraints: list[dict[str, object]] | None = None,
    reason_codes: list[str] | None = None,
    expected: ValidationStatus = ValidationStatus.VALID,
) -> RequestInterpretation:
    payload = {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-10-06T22:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": "a" * 64,
        "instruction_origin": "direct-user",
        "action": "implement",
        "requested_effect": "mutate",
        "continuation_mode": "new",
        "target": {
            "system": "github",
            "resource_kind": kind,
            "repository": repository,
            "resource_id": resource_id,
        },
        "requested_outputs": ["implementation"],
        "constraints": constraints or [],
        "reason_codes": reason_codes or [],
        "evidence_references": [],
    }
    result = validate_request_interpretation(payload)
    assert result.status is expected
    assert result.record is not None
    return RequestInterpretation(result.record)


def test_over_64_population_exact_issue_target_admits_one_member() -> None:
    population = tuple(range(1, 203))
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=population,
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="issue", resource_id="150"),
    )

    assert result.status is CohortAdmissionStatus.ADMITTED
    assert result.candidate_issue_numbers == (150,)
    assert result.candidate_count == 1
    assert result.population_membership_proven is True
    assert result.request_constraint_identity.startswith("request-")
    assert result.canonical_constraints_applied == (
        "request.target.system=github",
        "request.target.resource_kind=issue",
        "request.target.repository=Blummer92/agent-os",
        "request.target.resource_id=150",
    )
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_over_64_population_repository_target_fails_closed_without_truncation() -> None:
    population = tuple(range(1, 203))
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=population,
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="repository", resource_id=None),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == population
    assert result.candidate_count == 202
    assert result.fail_closed_reason == "cohort-admission.candidate-population-too-broad"
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_missing_request_constraints_fail_closed() -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=None,
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == ()
    assert result.fail_closed_reason == "cohort-admission.request-missing"


def test_candidate_outside_proven_population_fails_closed() -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 100)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="issue", resource_id="150"),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == (150,)
    assert result.population_membership_proven is False
    assert result.fail_closed_reason == "cohort-admission.candidate-not-in-population"


def test_identical_inputs_produce_identical_output() -> None:
    kwargs = dict(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="issue", resource_id="150"),
    )

    assert admit_request_cohort(**kwargs) == admit_request_cohort(**kwargs)


def test_admission_boundary_contains_no_backlog_ranking_or_operational_authority() -> None:
    from pathlib import Path
    import agent_os_execution_service.cohort_admission as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    forbidden = (
        "status:ready",
        "created_at",
        "popularity",
        "priority_score",
        "search_issues",
        "/search/issues",
        "issue.title",
        "issue.body",
        "select_executable_lanes",
        "Scheduler",
        "GitHubReadClient",
    )
    for token in forbidden:
        assert token not in source


def test_ambiguous_canonical_request_fails_closed() -> None:
    payload = {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-10-06T22:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": "b" * 64,
        "instruction_origin": "direct-user",
        "action": "unknown",
        "requested_effect": "read",
        "continuation_mode": "new",
        "target": {
            "system": "github",
            "resource_kind": "issue",
            "repository": REPOSITORY,
            "resource_id": "150",
        },
        "requested_outputs": [],
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }
    validation = validate_request_interpretation(payload)
    assert validation.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert validation.record is not None

    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=RequestInterpretation(validation.record),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == ()
    assert result.fail_closed_reason == "cohort-admission.request-ambiguous"


def test_bounded_repository_population_is_preserved_without_transformation() -> None:
    population = tuple(range(3, 3 + 2 * MAX_CANDIDATES, 2))
    assert len(population) == MAX_CANDIDATES

    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=population,
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="repository", resource_id=None),
    )

    assert result.status is CohortAdmissionStatus.ADMITTED
    assert result.candidate_issue_numbers == population
    assert result.population_issue_numbers == population
    assert result.reason_codes == ("cohort-admission.current",)


@pytest.mark.parametrize("target", [1, 64, 65, 202])
def test_exact_target_admission_is_position_independent(target: int) -> None:
    """Membership is identity, not position: no first-N truncation or ranking."""
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="issue", resource_id=str(target)),
    )

    assert result.status is CohortAdmissionStatus.ADMITTED
    assert result.candidate_issue_numbers == (target,)


def test_repository_request_constraints_without_membership_meaning_fail_closed() -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 11)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(
            kind="repository",
            resource_id=None,
            constraints=[{"name": "label", "value": "bug"}],
        ),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == ()
    assert result.fail_closed_reason == "cohort-admission.constraint-unsupported"
    assert result.execution_authorized is False


def test_conflicting_request_constraints_fail_closed() -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(
            kind="issue",
            resource_id="150",
            reason_codes=["request.conflicting-constraints"],
            expected=ValidationStatus.MANUAL_REVIEW_REQUIRED,
        ),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == ()
    assert result.fail_closed_reason == "cohort-admission.request-ambiguous"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {"kind": "issue", "resource_id": "150", "repository": "Other/repo"},
            "cohort-admission.repository-mismatch",
        ),
        (
            {"kind": "pull-request", "resource_id": "150"},
            "cohort-admission.request-not-applicable",
        ),
    ],
)
def test_inapplicable_requests_fabricate_no_cohort(kwargs: dict, reason: str) -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=tuple(range(1, 203)),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(**kwargs),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.candidate_issue_numbers == ()
    assert result.fail_closed_reason == reason


def test_empty_population_admits_nothing() -> None:
    result = admit_request_cohort(
        repository=REPOSITORY,
        population_issue_numbers=(),
        population_source_query=SOURCE_QUERY,
        request_interpretation=request(kind="repository", resource_id=None),
    )

    assert result.status is CohortAdmissionStatus.FAIL_CLOSED
    assert result.fail_closed_reason == "cohort-admission.candidate-population-empty"


def test_admission_imports_only_contract_and_capacity_owners() -> None:
    """No second scanner, GitHub client, selector, Scheduler, queue, or store."""
    import ast
    from pathlib import Path
    import agent_os_execution_service.cohort_admission as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {
        "__future__",
        "dataclasses",
        "enum",
        "hashlib",
        "json",
        "typing",
        "instructional_workflow_contracts.request_interpretation",
        "scripts.agent_os_candidate_packet.executable_lane_selection",
    }
    capacity_import = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "scripts.agent_os_candidate_packet.executable_lane_selection"
    )
    assert [alias.name for alias in capacity_import.names] == ["MAX_CANDIDATES"]
