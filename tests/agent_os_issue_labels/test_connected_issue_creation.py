from scripts.agent_os_issue_labels.connected_issue_creation import (
    DuplicateCandidateEvidence,
    DuplicateComparisonOutcome,
    DuplicateReviewDisposition,
    converge_connected_issue_creation,
    evaluate_duplicate_review_admission,
    managed_labels_for_create,
)
from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot
from tests.agent_os_issue_labels.lifecycle_admission import admitted_lifecycle_labels
from tests.agent_os_issue_labels.lifecycle_admission import refused_lifecycle_labels

FORM = ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ".github/labeler/agent-os-issue-label-map.yml"
BODY = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:github-service-agent

### Readiness candidate

status:ready

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write

### Prior scope, duplicate, and supersession review

Reviewed current open bug owners and found one distinct repair seam.
"""




def candidate(
    issue_number: int,
    *,
    state: str = "open",
    outcome: DuplicateComparisonOutcome | str = DuplicateComparisonOutcome.DISTINCT,
    objective: str = "same governed outcome",
    causal: str = "same causal seam",
    acceptance: str = "same acceptance boundary",
    boundary: str = "same ownership and scope boundary",
) -> DuplicateCandidateEvidence:
    return DuplicateCandidateEvidence(
        issue_number=issue_number,
        state=state,
        objective_evidence=objective,
        causal_seam_evidence=causal,
        acceptance_evidence=acceptance,
        boundary_evidence=boundary,
        comparison_outcome=outcome,
    )


def duplicate_admission(**kwargs):
    kwargs.setdefault("candidate_enumeration_complete", True)
    kwargs.setdefault("candidate_evidence", ())
    return evaluate_duplicate_review_admission(BODY, issue_form_path=FORM, **kwargs)


class Provider:
    def __init__(self, labels=()):
        self.snapshot = LiveIssueSnapshot("Blummer92/agent-os", 2144, BODY, tuple(labels), "open")
        self.writes = []
    def read(self, repository, issue_number): return self.snapshot
    def available_labels(self, repository): return ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")
    def add_label(self, repository, issue_number, label):
        self.writes.append(("add", label)); self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, self.snapshot.labels + (label,), "open")
    def remove_label(self, repository, issue_number, label):
        self.writes.append(("remove", label)); self.snapshot = LiveIssueSnapshot(repository, issue_number, BODY, tuple(x for x in self.snapshot.labels if x != label), "open")


def test_known_managed_labels_are_available_before_connected_create():
    assert set(managed_labels_for_create(BODY, issue_form_path=FORM, label_map_path=MAP)) == {"agent-os", "owner:github-service-agent", "status:ready", "type:bug"}


def test_distinct_bug_admission_allows_existing_create_flow():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
    )
    assert result.create_allowed is True
    assert result.next_operation == "create-then-canonical-readback-and-converge"
    assert result.canonical_issue_number is None


def test_2621_recurrence_routes_to_2283_without_create():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome=DuplicateComparisonOutcome.RECURRENCE),),
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2283
    assert result.next_operation == "append-recurrence-evidence-to-canonical-issue"


def test_2615_duplicate_routes_to_2602_without_create():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2602,
        candidate_evidence=(candidate(2602, outcome=DuplicateComparisonOutcome.DUPLICATE),),
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2602
    assert result.next_operation == "reuse-canonical-issue-no-create"


def test_focused_successor_requires_distinct_repair_seam():
    blocked = duplicate_admission(
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
    )
    admitted = duplicate_admission(
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
        distinct_repair_seam=True,
    )
    assert blocked.create_allowed is False
    assert blocked.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert admitted.create_allowed is True
    assert admitted.disposition is DuplicateReviewDisposition.FOCUSED_SUCCESSOR


def test_partial_overlap_and_missing_review_fail_closed():
    overlap = duplicate_admission(
        disposition=DuplicateReviewDisposition.PARTIAL_OVERLAP,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
    )
    no_review_body = BODY.split("### Prior scope, duplicate, and supersession review", 1)[0]
    missing = evaluate_duplicate_review_admission(
        no_review_body,
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_enumeration_complete=True,
        issue_form_path=FORM,
    )
    assert overlap.create_allowed is False
    assert overlap.next_operation == "manual-review-partial-overlap"
    assert missing.create_allowed is False
    assert "duplicate-review.prior-scope-evidence-missing" in missing.reason_codes


def test_connected_create_is_not_terminal_until_readback_converges():
    provider = Provider()
    result = converge_connected_issue_creation(provider, "Blummer92/agent-os", 2144, issue_form_path=FORM, label_map_path=MAP, lifecycle_admission=admitted_lifecycle_labels())
    assert result.terminal_success is True
    assert result.reconciliation.convergence_status == "converged"
    assert set(provider.snapshot.labels) == set(result.labels_for_create)


def test_missing_write_authority_cannot_claim_terminal_success():
    result = converge_connected_issue_creation(Provider(), "Blummer92/agent-os", 2144, issue_form_path=FORM, label_map_path=MAP, lifecycle_admission=refused_lifecycle_labels())
    assert result.terminal_success is False
    assert "connected-create-label-convergence-not-proven" in result.reason_codes


def test_ambiguous_manual_review_never_projects_create():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.MANUAL_REVIEW,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert result.next_operation == "manual-review-duplicate-admission-required"


def test_historical_issue_with_current_successor_uses_supplied_current_owner():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2602,
        candidate_evidence=(candidate(2602, outcome=DuplicateComparisonOutcome.RECURRENCE),),
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2602
    assert result.next_operation == "append-recurrence-evidence-to-canonical-issue"


def test_duplicate_admission_is_not_derived_from_issue_wording():
    differently_worded_body = BODY.replace(
        "Reviewed current open bug owners and found one distinct repair seam.",
        "Different title and wording; canonical evidence still identifies the existing owner.",
    )
    result = evaluate_duplicate_review_admission(
        differently_worded_body,
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome=DuplicateComparisonOutcome.DUPLICATE),),
        candidate_enumeration_complete=True,
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2283
    assert result.next_operation == "reuse-canonical-issue-no-create"


def test_focused_successor_rejects_non_boolean_repair_seam():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283),),
        distinct_repair_seam="false",
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert "duplicate-review.distinct-repair-seam-invalid" in result.reason_codes


def test_2660_incomplete_candidate_enumeration_fails_closed_before_create():
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=(candidate(2349),),
        candidate_enumeration_complete=False,
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-review.candidate-enumeration-incomplete",)


def test_2660_existing_owner_must_be_an_inspected_open_candidate():
    missing = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2602),),
    )
    closed = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, state="closed"),),
    )
    for result in (missing, closed):
        assert result.create_allowed is False
        assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
        assert result.reason_codes == (
            "duplicate-review.canonical-owner-not-inspected-open-candidate",
        )


def test_2660_candidate_comparison_requires_objective_causal_acceptance_and_boundary_evidence():
    incomplete = DuplicateCandidateEvidence(
        issue_number=2283,
        state="open",
        objective_evidence="same objective",
        causal_seam_evidence="same causal seam",
        acceptance_evidence="",
        boundary_evidence="same boundary",
    )
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(incomplete,),
    )
    assert result.create_allowed is False
    assert result.reason_codes == ("duplicate-review.candidate-evidence-invalid",)


def test_2660_one_incident_routes_three_existing_symptoms_and_one_distinct_bug():
    candidates = (
        candidate(2349, outcome=DuplicateComparisonOutcome.RECURRENCE),
        candidate(2647, outcome=DuplicateComparisonOutcome.RECURRENCE),
        candidate(2602, outcome=DuplicateComparisonOutcome.DUPLICATE),
    )
    cases = (
        duplicate_admission(disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER, canonical_issue_number=2349, candidate_evidence=candidates),
        duplicate_admission(disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER, canonical_issue_number=2647, candidate_evidence=candidates),
        duplicate_admission(disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER, canonical_issue_number=2602, candidate_evidence=candidates),
    )
    assert all(result.create_allowed is False for result in cases)
    assert [result.canonical_issue_number for result in cases] == [2349, 2647, 2602]
    assert cases[0].disposition is DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER
    assert cases[2].disposition is DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER
    distinct = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=(candidate(2816, outcome=DuplicateComparisonOutcome.DISTINCT),),
    )
    assert distinct.create_allowed is True
    assert distinct.canonical_issue_number is None
    assert distinct.next_operation == "create-then-canonical-readback-and-converge"


def test_2660_outcome_binding_routes_one_incident_across_owners():
    # Positive: per-candidate outcomes recorded during review route each
    # disposition; only an all-distinct inspection admits creation.
    owners = (
        candidate(2349, outcome=DuplicateComparisonOutcome.RECURRENCE),
        candidate(2647, outcome=DuplicateComparisonOutcome.RECURRENCE),
        candidate(2602, outcome=DuplicateComparisonOutcome.DUPLICATE),
    )
    recurrence = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2349,
        candidate_evidence=owners,
    )
    assert recurrence.create_allowed is False
    assert recurrence.disposition is DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER
    assert recurrence.canonical_issue_number == 2349
    assert recurrence.next_operation == "append-recurrence-evidence-to-canonical-issue"
    duplicate = duplicate_admission(
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2602,
        candidate_evidence=owners,
    )
    assert duplicate.create_allowed is False
    assert duplicate.disposition is DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER
    assert duplicate.canonical_issue_number == 2602
    assert duplicate.next_operation == "reuse-canonical-issue-no-create"


def test_2660_new_distinct_bug_fails_closed_when_any_open_candidate_is_not_distinct():
    mixed = (
        candidate(2349, outcome=DuplicateComparisonOutcome.DISTINCT),
        candidate(2602, outcome=DuplicateComparisonOutcome.RECURRENCE),
    )
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=mixed,
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert result.next_operation == "manual-review-duplicate-admission-required"
    assert result.reason_codes == ("duplicate-review.distinctness-unproven-for-candidate",)


def test_2660_unresolved_comparison_outcome_fails_closed_in_every_disposition():
    unresolved = (
        candidate(2349, outcome=DuplicateComparisonOutcome.DISTINCT),
        candidate(2602, outcome=DuplicateComparisonOutcome.UNRESOLVED),
    )
    distinct = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=unresolved,
    )
    recurrence = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2602,
        candidate_evidence=(candidate(2602, outcome=DuplicateComparisonOutcome.UNRESOLVED),),
    )
    for result in (distinct, recurrence):
        assert result.create_allowed is False
        assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
        assert result.reason_codes == ("duplicate-review.candidate-comparison-unresolved",)


def test_2660_recurrence_and_duplicate_require_canonical_outcome_agreement():
    mismatch_recurrence = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome=DuplicateComparisonOutcome.DISTINCT),),
    )
    mismatch_duplicate = duplicate_admission(
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome=DuplicateComparisonOutcome.RECURRENCE),),
    )
    for result in (mismatch_recurrence, mismatch_duplicate):
        assert result.create_allowed is False
        assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
        assert result.reason_codes == ("duplicate-review.canonical-outcome-disagrees",)
        assert result.canonical_issue_number == 2283


def test_2660_focused_successor_fails_closed_on_contradicting_outcome():
    contradicted = duplicate_admission(
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome=DuplicateComparisonOutcome.DUPLICATE),),
        distinct_repair_seam=True,
    )
    contradicted_elsewhere = duplicate_admission(
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        candidate_evidence=(
            candidate(2283, outcome=DuplicateComparisonOutcome.DISTINCT),
            candidate(2602, outcome=DuplicateComparisonOutcome.RECURRENCE),
        ),
        distinct_repair_seam=True,
    )
    for result in (contradicted, contradicted_elsewhere):
        assert result.create_allowed is False
        assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
        assert result.reason_codes == ("duplicate-review.focused-successor-seam-contradicted",)


def test_2660_outcome_string_values_coerce_to_canonical_outcomes():
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(candidate(2283, outcome="recurrence"),),
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER
    bogus = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=(candidate(2283, outcome="looks-similar"),),
    )
    assert bogus.create_allowed is False
    assert bogus.reason_codes == ("duplicate-review.candidate-evidence-invalid",)


def test_2660_caller_declared_outcomes_are_bound_not_semantically_verified():
    # Adversarial: identical causal-seam strings across every candidate, but
    # the caller records outcome=distinct for each. The admission binds the
    # declared claim (an auditable per-candidate record) and does not
    # semantically verify distinctness — semantic verification remains a
    # non-goal of #2660.
    identical = (
        candidate(2283, outcome=DuplicateComparisonOutcome.DISTINCT),
        candidate(2602, outcome=DuplicateComparisonOutcome.DISTINCT),
    )
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        candidate_evidence=identical,
    )
    assert result.create_allowed is True
    assert result.disposition is DuplicateReviewDisposition.NEW_DISTINCT_BUG


def test_2660_semantic_or_title_similarity_is_not_candidate_comparison_evidence():
    similarity_only = DuplicateCandidateEvidence(
        issue_number=2283,
        state="open",
        objective_evidence="same words in title",
        causal_seam_evidence="",
        acceptance_evidence="same words in acceptance heading",
        boundary_evidence="same label",
    )
    result = duplicate_admission(
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2283,
        candidate_evidence=(similarity_only,),
    )
    assert result.create_allowed is False
    assert result.reason_codes == ("duplicate-review.candidate-evidence-invalid",)
