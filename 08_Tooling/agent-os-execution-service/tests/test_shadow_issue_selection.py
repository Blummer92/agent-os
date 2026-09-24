from __future__ import annotations

from dataclasses import dataclass

from agent_os_execution_service.shadow_issue_selection import (
    ShadowSelectionStatus,
    select_shadow_issue,
)
from scripts.agent_os_candidate_packet.executable_lane_selection import CandidateIssueEvidence
from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_github_issue_provider.revision import issue_source_revision
from scripts.agent_os_issue_acceptance.github_issue_source import GitHubIssuePageResponse
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    evaluate_operating_mode_decision,
)


REPOSITORY = "Blummer92/agent-os"
REPOSITORY_SHA = "a" * 40
OTHER_REPOSITORY_SHA = "b" * 40
APPROVAL_ID = "approval:" + "1" * 64
ENVIRONMENT_ID = "environment-capability:" + "2" * 64
RETRIEVED_AT = "2026-09-22T19:00:00Z"


def raw_issue(number: int, *, body: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "body": body if body is not None else f"body-{number}",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-09-22T18:00:00Z",
        "updated_at": "2026-09-22T18:30:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [{"name": "agent-os"}],
    }
    item["source_revision"] = issue_source_revision(item)
    return item


def raw_pr(number: int) -> dict[str, object]:
    item = raw_issue(number)
    item["pull_request"] = {"url": f"https://api.github.com/repos/Blummer92/agent-os/pulls/{number}"}
    return item


@dataclass
class PageReader:
    pages: dict[int, GitHubIssuePageResponse]

    def read_issue_page(
        self, repository: str, *, page: int, per_page: int, state: str
    ) -> GitHubIssuePageResponse:
        assert repository == REPOSITORY
        assert per_page == 100
        assert state == "open"
        return self.pages[page]


@dataclass
class Transport:
    items: dict[int, dict[str, object]]

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        assert repository == REPOSITORY
        item = self.items.get(issue_number)
        if item is None:
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.NOT_FOUND
            )
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK,
            item=item,
        )


@dataclass
class EvidenceReader:
    candidates: dict[int, CandidateIssueEvidence]
    calls: int = 0

    def read_candidate_evidence(
        self, repository: str, issue_number: int
    ) -> CandidateIssueEvidence | None:
        assert repository == REPOSITORY
        self.calls += 1
        return self.candidates.get(issue_number)


class ExplodingEvidenceReader:
    def read_candidate_evidence(
        self, repository: str, issue_number: int
    ) -> CandidateIssueEvidence | None:
        raise AssertionError("candidate evidence must not be read after the capacity stop")


def authority(state: AuthorizationState) -> AuthorityProjection:
    evidence_id = APPROVAL_ID if state in {
        AuthorizationState.AUTHORIZED,
        AuthorizationState.STALE,
        AuthorizationState.NEEDS_DECISION,
    } else None
    return AuthorityProjection(state=state, evidence_id=evidence_id)


def candidate(
    item: dict[str, object],
    *,
    source_revision: str = REPOSITORY_SHA,
    implementation_authorization: AuthorizationState = AuthorizationState.AUTHORIZED,
) -> CandidateIssueEvidence:
    number = item["number"]
    assert type(number) is int
    revision = issue_source_revision(item)
    operational = build_issue_operational_state(
        IssueOperationalEvidence(
            repository=REPOSITORY,
            issue_number=number,
            source_revision=source_revision,
            observed_at=RETRIEVED_AT,
            evidence_ids=(revision, APPROVAL_ID),
            source_state=SourceState.COMPLETE,
            issue_state=IssueState.OPEN,
            lifecycle_stage=LifecycleStage.PLANNING,
            terminal_disposition=TerminalDisposition.NONE,
            readiness=ReadinessState.READY,
            implementation_authorization=authority(implementation_authorization),
            ready_for_review_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            execution_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            merge_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            closure_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            external_write_authorization=authority(AuthorizationState.NOT_AUTHORIZED),
            dependency_state=DependencyState.CLEAR,
            primary_claims=(),
            validation_state=ValidationState.NOT_RUN,
            freshness_state=FreshnessState.CURRENT,
            observed_labels=("agent-os",),
        )
    )
    environment = EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.NOT_VERIFIED,
        evidence_id=ENVIRONMENT_ID,
    )
    mode = evaluate_operating_mode_decision(operational, "build", environment)
    return CandidateIssueEvidence(
        issue_number=number,
        operational_state=operational,
        mode_decision=mode,
        dependency_depth=0,
    )


def terminal_reader(items: tuple[dict[str, object], ...]) -> PageReader:
    return PageReader(
        pages={
            1: GitHubIssuePageResponse(
                items=items,
                next_page=None,
                complete=True,
                terminal_page_proven=True,
            )
        }
    )


def test_complete_paginated_population_over_100_excludes_pull_requests() -> None:
    page_one = tuple(raw_issue(number) for number in range(1, 100)) + (raw_pr(9000),)
    page_two = (raw_issue(100), raw_issue(101))
    reader = PageReader(
        pages={
            1: GitHubIssuePageResponse(
                items=page_one,
                next_page=2,
                complete=True,
            ),
            2: GitHubIssuePageResponse(
                items=page_two,
                next_page=None,
                complete=True,
                terminal_page_proven=True,
            ),
        }
    )

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=reader,
        issue_transport=Transport({}),
        candidate_evidence_reader=ExplodingEvidenceReader(),
    )

    assert result.status is ShadowSelectionStatus.NO_SELECTION
    assert result.reason_codes == ("shadow-selection.candidate-population-too-broad",)
    assert result.scan_page_count == 2
    assert result.scan_item_count == 101
    assert len(result.population_issue_numbers) == 101
    assert 9000 not in result.population_issue_numbers


def test_incomplete_population_never_reads_candidate_evidence() -> None:
    reader = PageReader(
        pages={
            1: GitHubIssuePageResponse(
                items=(raw_issue(1),),
                next_page=None,
                complete=False,
                terminal_page_proven=False,
            )
        }
    )

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=reader,
        issue_transport=Transport({}),
        candidate_evidence_reader=ExplodingEvidenceReader(),
        candidate_issue_numbers=(1,),
    )

    assert result.reason_codes == ("shadow-selection.population-incomplete",)


def test_more_than_64_narrowed_candidates_fails_before_evidence_reads() -> None:
    items = tuple(raw_issue(number) for number in range(1, 66))

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader(items),
        issue_transport=Transport({}),
        candidate_evidence_reader=ExplodingEvidenceReader(),
        candidate_issue_numbers=tuple(range(1, 66)),
    )

    assert result.reason_codes == ("shadow-selection.candidate-population-too-broad",)


def test_missing_candidate_evidence_fails_closed() -> None:
    item = raw_issue(10)
    reader = EvidenceReader({})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((item,)),
        issue_transport=Transport({10: item}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10,),
    )

    assert result.reason_codes == ("shadow-selection.candidate-evidence-incomplete",)
    assert reader.calls == 1


def test_scanned_issue_revision_must_be_preserved_in_operational_evidence() -> None:
    scanned = raw_issue(10)
    changed = raw_issue(10, body="different evidence revision")
    reader = EvidenceReader({10: candidate(changed)})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((scanned,)),
        issue_transport=Transport({10: scanned}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10,),
    )

    assert result.reason_codes == ("shadow-selection.candidate-revision-mismatch",)


def test_repository_revision_conflict_fails_closed() -> None:
    first = raw_issue(10)
    second = raw_issue(11)
    reader = EvidenceReader(
        {
            10: candidate(first, source_revision=REPOSITORY_SHA),
            11: candidate(second, source_revision=OTHER_REPOSITORY_SHA),
        }
    )

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((first, second)),
        issue_transport=Transport({10: first, 11: second}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10, 11),
    )

    assert result.reason_codes == ("shadow-selection.repository-revision-conflict",)


def test_existing_selector_semantics_choose_lower_issue_number_without_calling_it_priority() -> None:
    low = raw_issue(10)
    high = raw_issue(11)
    reader = EvidenceReader({10: candidate(low), 11: candidate(high)})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((high, low)),
        issue_transport=Transport({10: low, 11: high}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(11, 10),
    )

    assert result.status is ShadowSelectionStatus.SELECTED
    assert result.selected_issue_number == 10
    assert result.selection is not None
    assert tuple(item.issue_number for item in result.selection.rank_evidence) == (10, 11)
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_explicit_request_order_is_forwarded_to_existing_selector() -> None:
    first = raw_issue(10)
    second = raw_issue(11)
    reader = EvidenceReader({10: candidate(first), 11: candidate(second)})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((first, second)),
        issue_transport=Transport({10: first, 11: second}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10, 11),
        explicit_request_order=(11, 10),
    )

    assert result.selected_issue_number == 11


def test_non_executable_candidates_return_no_selection() -> None:
    item = raw_issue(10)
    reader = EvidenceReader(
        {
            10: candidate(
                item,
                implementation_authorization=AuthorizationState.NOT_AUTHORIZED,
            )
        }
    )

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((item,)),
        issue_transport=Transport({10: item}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10,),
    )

    assert result.status is ShadowSelectionStatus.NO_SELECTION
    assert result.reason_codes == ("shadow-selection.selector-no-executable-lane",)
    assert result.selection is not None
    assert result.selection.selected_lanes == ()


def test_selected_issue_is_reacquired_and_bound_to_current_issue_revision() -> None:
    item = raw_issue(10)
    reader = EvidenceReader({10: candidate(item)})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((item,)),
        issue_transport=Transport({10: item}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10,),
    )

    assert result.status is ShadowSelectionStatus.SELECTED
    assert result.selected_issue_revision == issue_source_revision(item)
    assert result.repository_source_revision == REPOSITORY_SHA
    assert result.reason_codes == ("shadow-selection.current",)


def test_selected_issue_drift_requires_replan() -> None:
    scanned = raw_issue(10)
    changed = raw_issue(10, body="changed after population scan")
    reader = EvidenceReader({10: candidate(scanned)})

    result = select_shadow_issue(
        repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
        campaign_id="campaign-2832",
        page_reader=terminal_reader((scanned,)),
        issue_transport=Transport({10: changed}),
        candidate_evidence_reader=reader,
        candidate_issue_numbers=(10,),
    )

    assert result.status is ShadowSelectionStatus.REPLAN_REQUIRED
    assert result.reason_codes == ("shadow-selection.selected-issue-changed",)
    assert result.selected_issue_number is None
    assert result.selected_issue_revision is None