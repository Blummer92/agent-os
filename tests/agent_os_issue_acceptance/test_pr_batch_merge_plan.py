import pytest

from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import (
    PrBatchDisposition,
    PrBatchItemEvidence,
    build_pr_batch_merge_plan,
    normalize_finite_pr_targets,
)


def ev(number, *, state="open", admission="applicable", blocker="none", head=None):
    return PrBatchItemEvidence(
        pull_request_number=number,
        head_sha=head or f"head-{number}",
        base_branch="main",
        state=state,
        merge_admission_status=admission,
        blocker_scope=blocker,
    )


def test_finite_ordered_list_is_accepted_and_duplicates_normalize():
    assert normalize_finite_pr_targets([101, 102, 101, 103]) == (101, 102, 103)
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101, 102, 101, 103],
        evidence=[ev(103), ev(101), ev(102)],
    )
    assert [item.pull_request_number for item in plan.items] == [101, 102, 103]
    assert all(item.disposition is PrBatchDisposition.CANDIDATE for item in plan.items)
    assert plan.merge_authorized is False
    assert plan.side_effects_performed is False


@pytest.mark.parametrize("targets", [[], ["*"], [0], [-1], [True]])
def test_empty_wildcard_or_unbounded_style_targets_are_rejected(targets):
    with pytest.raises(ValueError):
        normalize_finite_pr_targets(targets)


def test_terminal_pr_is_classified_without_mutation_authority():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, state="merged")],
    )
    assert plan.items[0].disposition is PrBatchDisposition.ALREADY_TERMINAL
    assert plan.items[0].merge_authorized is False


def test_changed_head_requires_new_evidence_not_old_plan_authority():
    first = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, head="head-a")],
    )
    assert first.items[0].observed_head_sha == "head-a"
    assert first.items[0].requires_pre_merge_reacquisition is True
    second = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, head="head-b", admission="stale", blocker="item")],
    )
    assert second.items[0].disposition is PrBatchDisposition.ITEM_LOCAL_BLOCKED


def test_changed_main_is_explicit_plan_identity_and_requires_reacquisition():
    first = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102], evidence=[ev(101), ev(102)]
    )
    second = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-b",
        requested_pull_requests=[101, 102], evidence=[ev(101), ev(102)]
    )
    assert first.base_revision != second.base_revision
    assert all(item.requires_pre_merge_reacquisition for item in second.items)


def test_missing_or_ambiguous_merge_authority_is_item_local_blocked():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102],
        evidence=[ev(101, admission="needs-decision", blocker="item"), ev(102)],
    )
    assert [item.disposition for item in plan.items] == [
        PrBatchDisposition.ITEM_LOCAL_BLOCKED,
        PrBatchDisposition.CANDIDATE,
    ]
    assert plan.halt_remaining is False


def test_shared_blocker_halts_remaining_batch():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102, 103],
        evidence=[ev(101), ev(102, admission="blocked", blocker="shared"), ev(103)],
    )
    assert [item.pull_request_number for item in plan.items] == [101, 102]
    assert plan.items[-1].disposition is PrBatchDisposition.SHARED_BLOCKED
    assert plan.halt_remaining is True


def test_evidence_must_cover_exact_normalized_batch():
    with pytest.raises(ValueError):
        build_pr_batch_merge_plan(
            repository="Blummer92/agent-os", base_revision="main-a",
            requested_pull_requests=[101, 102], evidence=[ev(101)]
        )
