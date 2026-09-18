from scripts.agent_os_issue_labels.connected_issue_creation import (
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
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
        issue_form_path=FORM,
    )
    assert result.create_allowed is True
    assert result.next_operation == "create-then-canonical-readback-and-converge"
    assert result.canonical_issue_number is None


def test_2621_recurrence_routes_to_2283_without_create():
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2283,
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2283
    assert result.next_operation == "append-recurrence-evidence-to-canonical-issue"


def test_2615_duplicate_routes_to_2602_without_create():
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.DUPLICATE_EXISTING_OWNER,
        canonical_issue_number=2602,
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2602
    assert result.next_operation == "reuse-canonical-issue-no-create"


def test_focused_successor_requires_distinct_repair_seam():
    blocked = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        issue_form_path=FORM,
    )
    admitted = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        distinct_repair_seam=True,
        issue_form_path=FORM,
    )
    assert blocked.create_allowed is False
    assert blocked.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert admitted.create_allowed is True
    assert admitted.disposition is DuplicateReviewDisposition.FOCUSED_SUCCESSOR


def test_partial_overlap_and_missing_review_fail_closed():
    overlap = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.PARTIAL_OVERLAP,
        canonical_issue_number=2283,
        issue_form_path=FORM,
    )
    no_review_body = BODY.split("### Prior scope, duplicate, and supersession review", 1)[0]
    missing = evaluate_duplicate_review_admission(
        no_review_body,
        disposition=DuplicateReviewDisposition.NEW_DISTINCT_BUG,
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
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.MANUAL_REVIEW,
        canonical_issue_number=2283,
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert result.next_operation == "manual-review-duplicate-admission-required"


def test_historical_issue_with_current_successor_uses_supplied_current_owner():
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.RECURRENCE_EXISTING_OWNER,
        canonical_issue_number=2602,
        issue_form_path=FORM,
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
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.canonical_issue_number == 2283
    assert result.next_operation == "reuse-canonical-issue-no-create"


def test_focused_successor_rejects_non_boolean_repair_seam():
    result = evaluate_duplicate_review_admission(
        BODY,
        disposition=DuplicateReviewDisposition.FOCUSED_SUCCESSOR,
        canonical_issue_number=2283,
        distinct_repair_seam="false",
        issue_form_path=FORM,
    )
    assert result.create_allowed is False
    assert result.disposition is DuplicateReviewDisposition.MANUAL_REVIEW
    assert "duplicate-review.distinct-repair-seam-invalid" in result.reason_codes
