"""Canonical request/mission cohort admission for Shadow Navigation (#3328).

Owned semantically by the ChatGPT Orchestrator. This module is a deterministic
filtering boundary only: it proves which issues belong to the candidate universe
for one canonical request. It never ranks candidates, invents backlog priority,
reads GitHub, or creates execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Literal

from instructional_workflow_contracts.request_interpretation import RequestInterpretation
from scripts.agent_os_candidate_packet.executable_lane_selection import MAX_CANDIDATES


class CohortAdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    FAIL_CLOSED = "fail-closed"


REASON_CODES = frozenset(
    {
        "cohort-admission.current",
        "cohort-admission.request-missing",
        "cohort-admission.request-not-applicable",
        "cohort-admission.request-ambiguous",
        "cohort-admission.repository-mismatch",
        "cohort-admission.candidate-not-in-population",
        "cohort-admission.candidate-population-empty",
        "cohort-admission.candidate-population-too-broad",
    }
)


def _population_identity(
    repository: str, population_issue_numbers: tuple[int, ...], source_query: str
) -> str:
    payload = {
        "repository": repository,
        "source_query": source_query,
        "issue_numbers": list(population_issue_numbers),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "shadow-population-v1:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CohortAdmissionResult:
    repository: str
    population_issue_numbers: tuple[int, ...]
    population_source_query: str
    population_identity: str
    request_constraint_identity: str | None
    canonical_constraints_applied: tuple[str, ...]
    candidate_issue_numbers: tuple[int, ...]
    candidate_count: int
    population_membership_proven: bool
    status: CohortAdmissionStatus
    reason_codes: tuple[str, ...]
    fail_closed_reason: str | None
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in ("population_issue_numbers", "candidate_issue_numbers"):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(value) is not int or value < 1 for value in values
            ):
                raise TypeError(f"{name} must be an exact tuple of positive integers")
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{name} must be sorted and unique")
        if type(self.canonical_constraints_applied) is not tuple or any(
            type(value) is not str or not value for value in self.canonical_constraints_applied
        ):
            raise TypeError("canonical_constraints_applied must be exact non-empty strings")
        if type(self.candidate_count) is not int or self.candidate_count != len(
            self.candidate_issue_numbers
        ):
            raise ValueError("candidate_count must equal candidate_issue_numbers length")
        if type(self.population_membership_proven) is not bool:
            raise TypeError("population_membership_proven must be an exact bool")
        if not isinstance(self.status, CohortAdmissionStatus):
            raise TypeError("status must be CohortAdmissionStatus")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or any(reason not in REASON_CODES for reason in reasons):
            raise ValueError("reason_codes contains an unsupported reason")
        object.__setattr__(self, "reason_codes", reasons)
        if self.status is CohortAdmissionStatus.ADMITTED:
            if self.fail_closed_reason is not None:
                raise ValueError("admitted result cannot carry fail_closed_reason")
            if not self.population_membership_proven:
                raise ValueError("admitted result requires population membership proof")
            if not 1 <= self.candidate_count <= MAX_CANDIDATES:
                raise ValueError("admitted cohort must contain 1..MAX_CANDIDATES issues")
        elif self.fail_closed_reason not in reasons:
            raise ValueError("fail-closed result must name its reason")
        if self.execution_authorized is not False or self.side_effects_performed is not False:
            raise ValueError("cohort admission cannot authorize execution or side effects")


def admit_request_cohort(
    *,
    repository: str,
    population_issue_numbers: tuple[int, ...],
    population_source_query: str,
    request_interpretation: RequestInterpretation | None,
) -> CohortAdmissionResult:
    """Project one canonical request into a bounded candidate cohort.

    The only currently governed membership rule is an exact GitHub issue target
    from the canonical request-interpretation-v1 record. That target is identity
    evidence, not rank. A repository target denotes the complete proven source
    population and is admitted only when already within the bounded capacity.
    Unknown targets and request records with unresolved reason codes fail closed
    rather than promoting arbitrary constraints, labels, prose, or operator
    filtering into cohort authority.
    """

    if type(repository) is not str or repository.count("/") != 1:
        raise ValueError("repository must use owner/name form")
    if type(population_issue_numbers) is not tuple or any(
        type(value) is not int or value < 1 for value in population_issue_numbers
    ):
        raise TypeError("population_issue_numbers must be an exact tuple of positive integers")
    population = tuple(sorted(set(population_issue_numbers)))
    if population != population_issue_numbers:
        raise ValueError("population_issue_numbers must be sorted and unique")
    if type(population_source_query) is not str or not population_source_query.strip():
        raise ValueError("population_source_query must be non-empty exact text")

    population_id = _population_identity(repository, population, population_source_query)

    def fail(
        reason: str,
        *,
        request_id: str | None = None,
        constraints: tuple[str, ...] = (),
        candidates: tuple[int, ...] = (),
        membership: bool = False,
    ) -> CohortAdmissionResult:
        return CohortAdmissionResult(
            repository=repository,
            population_issue_numbers=population,
            population_source_query=population_source_query,
            population_identity=population_id,
            request_constraint_identity=request_id,
            canonical_constraints_applied=constraints,
            candidate_issue_numbers=candidates,
            candidate_count=len(candidates),
            population_membership_proven=membership,
            status=CohortAdmissionStatus.FAIL_CLOSED,
            reason_codes=(reason,),
            fail_closed_reason=reason,
        )

    if request_interpretation is None:
        return fail("cohort-admission.request-missing")
    if type(request_interpretation) is not RequestInterpretation:
        raise TypeError("request_interpretation must be exact RequestInterpretation or None")

    record = request_interpretation.record
    payload = record.to_dict()
    request_id = record.record_id
    if payload.get("reason_codes"):
        return fail(
            "cohort-admission.request-ambiguous",
            request_id=request_id,
        )

    target = payload["target"]
    constraints = (
        f"request.target.system={target['system']}",
        f"request.target.resource_kind={target['resource_kind']}",
        f"request.target.repository={target['repository']}",
        f"request.target.resource_id={target['resource_id']}",
    )
    if target["system"] != "github" or target["resource_kind"] not in {"issue", "repository"}:
        return fail(
            "cohort-admission.request-not-applicable",
            request_id=request_id,
            constraints=constraints,
        )
    target_repository = target["repository"]
    if type(target_repository) is not str or target_repository.casefold() != repository.casefold():
        return fail(
            "cohort-admission.repository-mismatch",
            request_id=request_id,
            constraints=constraints,
        )
    if target["resource_kind"] == "repository":
        if target["resource_id"] is not None:
            return fail(
                "cohort-admission.request-ambiguous",
                request_id=request_id,
                constraints=constraints,
            )
        candidates = population
        membership = True
    else:
        raw_issue = target["resource_id"]
        try:
            issue_number = int(raw_issue)
        except (TypeError, ValueError):
            return fail(
                "cohort-admission.request-ambiguous",
                request_id=request_id,
                constraints=constraints,
            )
        if issue_number < 1 or str(issue_number) != raw_issue:
            return fail(
                "cohort-admission.request-ambiguous",
                request_id=request_id,
                constraints=constraints,
            )
        candidates = (issue_number,)
        membership = issue_number in set(population)
        if not membership:
            return fail(
                "cohort-admission.candidate-not-in-population",
                request_id=request_id,
                constraints=constraints,
                candidates=candidates,
                membership=False,
            )
    if not candidates:
        return fail(
            "cohort-admission.candidate-population-empty",
            request_id=request_id,
            constraints=constraints,
            candidates=candidates,
            membership=True,
        )
    if len(candidates) > MAX_CANDIDATES:
        return fail(
            "cohort-admission.candidate-population-too-broad",
            request_id=request_id,
            constraints=constraints,
            candidates=candidates,
            membership=True,
        )

    return CohortAdmissionResult(
        repository=repository,
        population_issue_numbers=population,
        population_source_query=population_source_query,
        population_identity=population_id,
        request_constraint_identity=request_id,
        canonical_constraints_applied=constraints,
        candidate_issue_numbers=candidates,
        candidate_count=len(candidates),
        population_membership_proven=True,
        status=CohortAdmissionStatus.ADMITTED,
        reason_codes=("cohort-admission.current",),
        fail_closed_reason=None,
    )
