from scripts.agent_os_cloud_build_reporting import (
    ManagedCommentSnapshot,
    OverallResult,
    PublicationAction,
    PullRequestResolutionCandidate,
    PullRequestState,
    normalize_cloud_build_evidence,
    plan_publication,
    reconcile_publication,
    render_comment_projection,
    resolve_pull_request,
)

REPO = "blummer92/agent-os"
SHA = "a" * 40


def evidence():
    return normalize_cloud_build_evidence(
        build_id="build-686",
        tested_sha=SHA,
        repository=REPO,
        overall_result=OverallResult.SUCCESS,
        terminal=True,
        source_complete=True,
        failed_step="none",
        exit_code=0,
    )


def resolved(e=None):
    e = e or evidence()
    return resolve_pull_request(
        e,
        candidates=(
            PullRequestResolutionCandidate(
                repository=REPO,
                pull_request_number=42,
                head_sha=SHA,
                state=PullRequestState.OPEN,
                evidence_source="canonical-pr-readback",
            ),
        ),
    )


def projection(e=None, r=None):
    e = e or evidence()
    r = r or resolved(e)
    return render_comment_projection(e, r)


def test_exact_target_without_managed_comment_plans_create():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(e, r, p, comments_complete=True, comments=())
    assert plan.action is PublicationAction.CREATE
    assert plan.pull_request_number == 42
    assert plan.tested_sha == SHA
    assert plan.execution_authorized is False
    assert plan.side_effects_performed is False


def test_wrong_sha_never_plans_mutation():
    e = evidence()
    wrong = resolve_pull_request(
        e,
        candidates=(
            PullRequestResolutionCandidate(
                repository=REPO,
                pull_request_number=42,
                head_sha="b" * 40,
                state=PullRequestState.OPEN,
                evidence_source="canonical-pr-readback",
            ),
        ),
    )
    p = render_comment_projection(e, wrong)
    plan = plan_publication(e, wrong, p, comments_complete=True, comments=())
    assert plan.action is PublicationAction.MANUAL_REVIEW
    assert "publication.target-unresolved" in plan.reason_codes


def test_existing_managed_comment_plans_deterministic_update_then_converges():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    existing = ManagedCommentSnapshot(10, p.stable_marker + "\nold report")
    plan = plan_publication(e, r, p, comments_complete=True, comments=(existing,))
    assert plan.action is PublicationAction.UPDATE
    assert plan.managed_comment_id == 10

    result = reconcile_publication(
        plan,
        provider_reported_success=True,
        readback_complete=True,
        comments=(ManagedCommentSnapshot(10, p.rendered_body),),
    )
    assert result.status == "converged"
    assert result.persisted_comment_id == 10
    assert result.retry_safe is False


def test_identical_managed_comment_is_noop():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(
        e,
        r,
        p,
        comments_complete=True,
        comments=(ManagedCommentSnapshot(10, p.rendered_body),),
    )
    assert plan.action is PublicationAction.NOOP
    result = reconcile_publication(
        plan,
        provider_reported_success=None,
        readback_complete=True,
        comments=(ManagedCommentSnapshot(10, p.rendered_body),),
    )
    assert result.status == "converged"
    assert result.reason_codes == ("publication.noop-current",)


def test_unrelated_human_comment_is_preserved_and_does_not_block_create():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    human = ManagedCommentSnapshot(7, "Please keep this human note.")
    plan = plan_publication(e, r, p, comments_complete=True, comments=(human,))
    assert plan.action is PublicationAction.CREATE
    assert plan.managed_comment_id is None


def test_multiple_managed_comments_fail_closed():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    comments = (
        ManagedCommentSnapshot(10, p.stable_marker + "\nold one"),
        ManagedCommentSnapshot(11, p.stable_marker + "\nold two"),
    )
    plan = plan_publication(e, r, p, comments_complete=True, comments=comments)
    assert plan.action is PublicationAction.MANUAL_REVIEW
    assert plan.reason_codes == ("publication.multiple-managed-comments",)


def test_incomplete_comment_readback_fails_closed_before_mutation():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(e, r, p, comments_complete=False, comments=())
    assert plan.action is PublicationAction.MANUAL_REVIEW
    assert plan.reason_codes == ("publication.comment-readback-incomplete",)


def test_provider_failure_with_complete_empty_readback_is_not_persisted():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(e, r, p, comments_complete=True, comments=())
    result = reconcile_publication(
        plan,
        provider_reported_success=False,
        readback_complete=True,
        comments=(),
    )
    assert result.status == "not-persisted"
    assert result.retry_safe is True
    assert result.merge_authorized is False
    assert result.review_authorized is False
    assert result.required_check_authorized is False


def test_uncertain_readback_never_allows_retry():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(e, r, p, comments_complete=True, comments=())
    result = reconcile_publication(
        plan,
        provider_reported_success=True,
        readback_complete=False,
        comments=(),
    )
    assert result.status == "uncertain"
    assert result.retry_safe is False


def test_update_must_persist_on_same_managed_comment_identity():
    e = evidence()
    r = resolved(e)
    p = projection(e, r)
    plan = plan_publication(
        e,
        r,
        p,
        comments_complete=True,
        comments=(ManagedCommentSnapshot(10, p.stable_marker + "\nold"),),
    )
    result = reconcile_publication(
        plan,
        provider_reported_success=True,
        readback_complete=True,
        comments=(ManagedCommentSnapshot(11, p.rendered_body),),
    )
    assert result.status == "uncertain"
    assert result.reason_codes == ("publication.update-target-mismatch",)
    assert result.retry_safe is False
