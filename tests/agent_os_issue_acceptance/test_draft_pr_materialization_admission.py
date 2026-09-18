from scripts.agent_os_issue_acceptance.draft_pr_materialization_admission import (
    evaluate_draft_pr_materialization,
)


REPOSITORY = "Blummer92/agent-os"
BASE = "a" * 40
HEAD = "b" * 40


def evaluate(**overrides):
    values = {
        "repository": REPOSITORY,
        "issue_number": 2593,
        "base_sha": BASE,
        "head_sha": HEAD,
        "changed_files": 1,
        "in_scope_changed_files": 1,
        "canonical_no_diff_permitted": False,
        "post_create_readback": False,
    }
    values.update(overrides)
    return evaluate_draft_pr_materialization(**values)


def test_2592_reproduction_changed_head_with_zero_net_diff_is_rejected():
    result = evaluate(changed_files=0, in_scope_changed_files=0)

    assert result.admitted is False
    assert result.disposition == "block-empty-diff"
    assert result.reason_codes == ("draft-pr-materialization.empty-diff",)


def test_create_then_delete_probe_cannot_satisfy_delivery():
    first_head = "c" * 40
    result = evaluate(head_sha=first_head, changed_files=0, in_scope_changed_files=0)

    assert first_head != BASE
    assert result.admitted is False
    assert result.changed_files == 0


def test_ordinary_in_scope_net_diff_is_admitted():
    result = evaluate(changed_files=2, in_scope_changed_files=2)

    assert result.admitted is True
    assert result.disposition == "create-primary-pr"
    assert result.reason_codes == ("draft-pr-materialization.in-scope-diff-present",)


def test_unrelated_diff_does_not_satisfy_implementation_delivery():
    result = evaluate(changed_files=2, in_scope_changed_files=0)

    assert result.admitted is False
    assert result.disposition == "block-out-of-scope-diff"
    assert result.reason_codes == ("draft-pr-materialization.no-in-scope-diff",)


def test_no_diff_exception_requires_explicit_canonical_contract():
    ordinary = evaluate(changed_files=0, in_scope_changed_files=0)
    canonical = evaluate(
        changed_files=0,
        in_scope_changed_files=0,
        canonical_no_diff_permitted=True,
    )

    assert ordinary.admitted is False
    assert canonical.admitted is True
    assert canonical.disposition == "allow-canonical-no-diff"


def test_post_create_zero_file_readback_is_invalid_implementation_evidence():
    result = evaluate(
        changed_files=0,
        in_scope_changed_files=0,
        post_create_readback=True,
    )

    assert result.admitted is False
    assert result.reason_codes == ("draft-pr-materialization.post-create-empty-diff",)


def test_invalid_scope_counts_fail_closed():
    result = evaluate(changed_files=1, in_scope_changed_files=2)

    assert result.admitted is False
    assert result.disposition == "block-invalid-evidence"
    assert result.reason_codes == ("draft-pr-materialization.scope-count-invalid",)


def test_guard_never_grants_repository_or_lifecycle_authority():
    result = evaluate()

    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.side_effects_performed is False
