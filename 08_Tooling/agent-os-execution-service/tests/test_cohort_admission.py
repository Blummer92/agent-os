from __future__ import annotations

from instructional_workflow_contracts.request_interpretation import (
    RequestInterpretation,
    validate_request_interpretation,
)
from instructional_workflow_contracts.common import ValidationStatus

from agent_os_execution_service.cohort_admission import (
    CohortAdmissionStatus,
    admit_request_cohort,
)


REPOSITORY = "Blummer92/agent-os"
SOURCE_QUERY = "repo=Blummer92/agent-os state=open"


def request(*, kind: str, resource_id: str | None) -> RequestInterpretation:
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
            "repository": REPOSITORY,
            "resource_id": resource_id,
        },
        "requested_outputs": ["implementation"],
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }
    result = validate_request_interpretation(payload)
    assert result.status is ValidationStatus.VALID
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
