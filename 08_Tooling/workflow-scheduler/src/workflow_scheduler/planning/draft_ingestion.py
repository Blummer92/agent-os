from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

PROPOSAL_VERSION = "1.0"
_STATUS_VALUES = frozenset(
    {"eligible", "blocked", "stale", "invalid", "needs-decision"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DraftTaskProposal:
    proposal_version: str
    proposal_id: str
    handoff_digest: str
    graph_digest: str
    planning_result_digest: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    evaluator_commit_sha: str
    supplied_node_ids: tuple[str, ...]
    cohort_summaries: tuple[Any, ...]
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str
    created_at: str
    eligibility_status: Literal["eligible"] = "eligible"
    authorization_status: Literal["not-evaluated"] = field(
        default="not-evaluated", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.proposal_version != PROPOSAL_VERSION:
            raise ValueError("unsupported proposal_version")
        if self.eligibility_status != "eligible":
            raise ValueError("draft proposals must remain eligible and unapproved")
        _timestamp(self.created_at)
        node_ids = tuple(self.supplied_node_ids)
        if node_ids != tuple(sorted(node_ids)) or len(node_ids) != len(set(node_ids)):
            raise ValueError("supplied_node_ids must be sorted and unique")
        object.__setattr__(self, "supplied_node_ids", node_ids)
        cohorts = tuple(self.cohort_summaries)
        if not all(
            hasattr(item, "node_ids")
            and hasattr(item, "classification")
            and hasattr(item, "reason_codes")
            for item in cohorts
        ):
            raise TypeError("cohort_summaries must preserve upstream cohort values")
        object.__setattr__(self, "cohort_summaries", cohorts)
        expected_id = _digest(
            _proposal_public_identity_payload(
                proposal_version=self.proposal_version,
                handoff_digest=self.handoff_digest,
                graph_digest=self.graph_digest,
                planning_result_digest=self.planning_result_digest,
                repository=self.repository,
                base_branch=self.base_branch,
                evaluated_repository_sha=self.evaluated_repository_sha,
                evaluator_commit_sha=self.evaluator_commit_sha,
                supplied_node_ids=self.supplied_node_ids,
                cohort_summaries=self.cohort_summaries,
                issueplan_current_state_evidence_id=(
                    self.issueplan_current_state_evidence_id
                ),
                repository_state_evidence_id=self.repository_state_evidence_id,
            )
        )
        if self.proposal_id != expected_id:
            raise ValueError("proposal_id does not match proposal content")


@dataclass(frozen=True, slots=True, kw_only=True)
class DraftTaskProposalResult:
    status: str
    proposals: tuple[DraftTaskProposal, ...]
    reason_codes: tuple[str, ...]
    handoff_validation: Any | None
    issueplan_comparison: Any | None
    repository_state_validation: Any | None
    authorization_status: Literal["not-evaluated"] = field(
        default="not-evaluated", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _STATUS_VALUES:
            raise ValueError("unsupported draft-ingestion status")
        if not all(isinstance(item, DraftTaskProposal) for item in self.proposals):
            raise TypeError("proposals must contain DraftTaskProposal values")
        object.__setattr__(self, "proposals", tuple(self.proposals))
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))


def build_draft_task_proposals(
    transported_handoff: object,
    issueplan_current_state_evidence: object,
    repository_state_evidence: object,
    *,
    created_at: str,
) -> DraftTaskProposalResult:
    """Validate supplied evidence and emit one immutable, unapproved proposal.

    The function performs no clock read, persistence, task creation, live probe,
    repository mutation, adapter execution, or external I/O.
    """

    try:
        _timestamp(created_at)
        api = _load_upstream_api()
    except (TypeError, ValueError, ImportError):
        return _result("invalid", ("hard-dependency-unmet",))

    handoff_validation = api["validate_handoff"](transported_handoff)
    if getattr(handoff_validation.outcome, "value", None) == "invalid":
        return _result(
            "invalid",
            handoff_validation.reason_codes,
            handoff_validation=handoff_validation,
        )

    handoff = _coerce_handoff(transported_handoff, api)
    if handoff is None:
        return _result(
            "invalid",
            (*handoff_validation.reason_codes, "hard-dependency-unmet"),
            handoff_validation=handoff_validation,
        )

    if not isinstance(issueplan_current_state_evidence, api["issueplan_evidence"]):
        return _result(
            "blocked",
            ("hard-dependency-unmet",),
            handoff_validation=handoff_validation,
        )
    issueplan_comparison = api["compare_issueplan"](
        issueplan_current_state_evidence,
        issueplan_current_state_evidence,
    )

    if repository_state_evidence is None:
        return _result(
            "blocked",
            ("hard-dependency-unmet",),
            handoff_validation=handoff_validation,
            issueplan_comparison=issueplan_comparison,
        )
    repository_state_validation = api["validate_repository"](
        repository_state_evidence
    )

    mapped_status = _strongest_status(
        _issueplan_status(issueplan_comparison),
        _repository_status(repository_state_validation),
    )
    upstream_reasons = _upstream_reasons(
        handoff_validation,
        issueplan_comparison,
        repository_state_validation,
    )
    if mapped_status != "eligible":
        return _result(
            mapped_status,
            upstream_reasons,
            handoff_validation=handoff_validation,
            issueplan_comparison=issueplan_comparison,
            repository_state_validation=repository_state_validation,
        )

    if not _bindings_match(
        handoff,
        issueplan_current_state_evidence,
        repository_state_validation,
    ):
        return _result(
            "stale",
            (*upstream_reasons, "planning-state-mismatch"),
            handoff_validation=handoff_validation,
            issueplan_comparison=issueplan_comparison,
            repository_state_validation=repository_state_validation,
        )

    identity_payload = _proposal_public_identity_payload(
        proposal_version=PROPOSAL_VERSION,
        handoff_digest=handoff.handoff_digest,
        graph_digest=handoff.graph_digest,
        planning_result_digest=handoff.planning_result_digest,
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        evaluator_commit_sha=handoff.evaluator_commit_sha,
        supplied_node_ids=tuple(handoff.supplied_node_ids),
        cohort_summaries=tuple(handoff.cohort_summaries),
        issueplan_current_state_evidence_id=(
            issueplan_current_state_evidence.evidence_id
        ),
        repository_state_evidence_id=repository_state_validation.evidence_id,
    )
    proposal = DraftTaskProposal(
        proposal_version=PROPOSAL_VERSION,
        proposal_id=_digest(identity_payload),
        handoff_digest=handoff.handoff_digest,
        graph_digest=handoff.graph_digest,
        planning_result_digest=handoff.planning_result_digest,
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        evaluator_commit_sha=handoff.evaluator_commit_sha,
        supplied_node_ids=tuple(handoff.supplied_node_ids),
        cohort_summaries=tuple(handoff.cohort_summaries),
        issueplan_current_state_evidence_id=(
            issueplan_current_state_evidence.evidence_id
        ),
        repository_state_evidence_id=repository_state_validation.evidence_id,
        created_at=created_at,
    )
    return _result(
        "eligible",
        ("approval-not-evaluated",),
        proposals=(proposal,),
        handoff_validation=handoff_validation,
        issueplan_comparison=issueplan_comparison,
        repository_state_validation=repository_state_validation,
    )


def _load_upstream_api() -> dict[str, Any]:
    from scripts.agent_os_execution_capabilities import (
        validate_repository_state_evidence,
    )
    from scripts.agent_os_issue_acceptance import (
        HandoffCohort,
        IssuePlanCurrentStateEvidence,
        SchedulerPlanningHandoff,
        compare_issueplan_current_state,
        validate_scheduler_planning_handoff,
    )

    return {
        "cohort": HandoffCohort,
        "handoff": SchedulerPlanningHandoff,
        "issueplan_evidence": IssuePlanCurrentStateEvidence,
        "compare_issueplan": compare_issueplan_current_state,
        "validate_handoff": validate_scheduler_planning_handoff,
        "validate_repository": validate_repository_state_evidence,
    }


def _coerce_handoff(value: object, api: Mapping[str, Any]) -> Any | None:
    if isinstance(value, api["handoff"]):
        return value
    if not isinstance(value, Mapping):
        return None
    raw = dict(value)
    try:
        cohorts = tuple(
            item
            if isinstance(item, api["cohort"])
            else api["cohort"](
                node_ids=tuple(item["node_ids"]),
                classification=item["classification"],
                reason_codes=tuple(item["reason_codes"]),
            )
            for item in raw["cohort_summaries"]
        )
        return api["handoff"](
            contract_version=raw["contract_version"],
            planning_result_version=raw["planning_result_version"],
            evaluator_commit_sha=raw["evaluator_commit_sha"],
            repository=raw["repository"],
            base_branch=raw["base_branch"],
            evaluated_repository_sha=raw["evaluated_repository_sha"],
            supplied_node_ids=tuple(raw["supplied_node_ids"]),
            graph_digest=raw["graph_digest"],
            planning_result_digest=raw["planning_result_digest"],
            cohort_summaries=cohorts,
            created_at=raw["created_at"],
            handoff_digest=raw["handoff_digest"],
        )
    except (KeyError, TypeError, ValueError):
        return None


def _issueplan_status(comparison: object) -> str:
    value = getattr(getattr(comparison, "outcome", None), "value", None)
    return {
        "current": "eligible",
        "stale": "stale",
        "blocked": "blocked",
        "invalid": "invalid",
        "needs-decision": "needs-decision",
    }.get(value, "blocked")


def _repository_status(result: object) -> str:
    return {
        "valid": "eligible",
        "stale": "stale",
        "blocked": "blocked",
        "invalid": "invalid",
        "needs-decision": "needs-decision",
    }.get(getattr(result, "outcome", None), "blocked")


def _strongest_status(*values: str) -> str:
    rank = {
        "eligible": 0,
        "stale": 1,
        "blocked": 2,
        "needs-decision": 3,
        "invalid": 4,
    }
    return max(values, key=rank.__getitem__)


def _upstream_reasons(*results: object) -> tuple[str, ...]:
    values: set[str] = set()
    for result in results:
        for code in getattr(result, "reason_codes", ()):
            if code != "external-revalidation-required":
                values.add(code)
    return tuple(sorted(values))


def _bindings_match(handoff: Any, issueplan: Any, repository: Any) -> bool:
    identity = repository.repository_identity
    if identity is None or repository.tested_sha is None:
        return False
    canonical_repository = f"{identity.owner}/{identity.repository}"
    cohorts = _canonical_cohorts(handoff.cohort_summaries)
    covered = tuple(
        sorted(node_id for cohort in cohorts for node_id in cohort["node_ids"])
    )
    expected_nodes = tuple(sorted(handoff.supplied_node_ids))
    return all(
        (
            handoff.repository.casefold() == canonical_repository.casefold(),
            issueplan.repository is not None
            and handoff.repository.casefold() == issueplan.repository.casefold(),
            handoff.base_branch == issueplan.base_branch == repository.base_ref,
            handoff.evaluated_repository_sha
            == issueplan.evaluated_repository_sha
            == repository.tested_sha,
            issueplan.graph_reference == handoff.graph_digest,
            issueplan.planning_result_reference == handoff.planning_result_digest,
            issueplan.handoff_reference == handoff.handoff_digest,
            tuple(issueplan.supplied_node_ids) == expected_nodes,
            covered == expected_nodes,
            issueplan.implementation_contract_fingerprint
            == repository.contract_fingerprint,
        )
    )


def _proposal_public_identity_payload(
    *,
    proposal_version: str,
    handoff_digest: str,
    graph_digest: str,
    planning_result_digest: str,
    repository: str,
    base_branch: str,
    evaluated_repository_sha: str,
    evaluator_commit_sha: str,
    supplied_node_ids: tuple[str, ...],
    cohort_summaries: tuple[Any, ...],
    issueplan_current_state_evidence_id: str,
    repository_state_evidence_id: str,
) -> dict[str, Any]:
    return {
        "proposal_version": proposal_version,
        "handoff_digest": handoff_digest,
        "graph_digest": graph_digest,
        "planning_result_digest": planning_result_digest,
        "repository": repository.casefold(),
        "base_branch": base_branch,
        "evaluated_repository_sha": evaluated_repository_sha,
        "evaluator_commit_sha": evaluator_commit_sha,
        "supplied_node_ids": list(supplied_node_ids),
        "cohort_summaries": _canonical_cohorts(cohort_summaries),
        "issueplan_current_state_evidence_id": issueplan_current_state_evidence_id,
        "repository_state_evidence_id": repository_state_evidence_id,
        "eligibility_status": "eligible",
        "authorization_status": "not-evaluated",
        "execution_authorized": False,
    }


def _canonical_cohorts(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, (tuple, list)):
        raise TypeError("cohort_summaries must be a sequence")
    cohorts: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, Mapping):
            node_ids = item["node_ids"]
            classification = item["classification"]
            reason_codes = item["reason_codes"]
        else:
            node_ids = item.node_ids
            classification = item.classification
            reason_codes = item.reason_codes
        cohorts.append(
            {
                "node_ids": sorted(set(node_ids)),
                "classification": classification,
                "reason_codes": sorted(set(reason_codes)),
            }
        )
    precedence = {
        "blocked": 0,
        "needs-decision": 1,
        "sequencing-review": 2,
        "parallel-candidate": 3,
    }
    return sorted(
        cohorts,
        key=lambda item: (
            precedence.get(item["classification"], len(precedence)),
            item["node_ids"],
        ),
    )


def _result(
    status: str,
    reason_codes: tuple[str, ...] | list[str],
    *,
    proposals: tuple[DraftTaskProposal, ...] = (),
    handoff_validation: object | None = None,
    issueplan_comparison: object | None = None,
    repository_state_validation: object | None = None,
) -> DraftTaskProposalResult:
    return DraftTaskProposalResult(
        status=status,
        proposals=proposals,
        reason_codes=tuple(reason_codes),
        handoff_validation=handoff_validation,
        issueplan_comparison=issueplan_comparison,
        repository_state_validation=repository_state_validation,
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("created_at must be an RFC3339 UTC string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("created_at must be an RFC3339 UTC string") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
