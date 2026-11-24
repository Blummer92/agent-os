"""A reporting projection must be rendered from its exact resolved PR."""
import json
from dataclasses import fields

from scripts.agent_os_cloud_build_reporting import (
    CloudBuildCommentProjection, OverallResult, PublicationAction,
    PullRequestResolutionCandidate, PullRequestState,
    normalize_cloud_build_evidence, plan_publication, render_comment_projection,
    resolve_pull_request, serialize_projection,
)


def inputs():
    evidence = normalize_cloud_build_evidence(
        build_id="ordinary-fixture", tested_sha="a" * 40, repository="example/test",
        overall_result=OverallResult.SUCCESS, terminal=True, source_complete=True,
        failed_step="none", exit_code=0,
    )

    def resolve(pr_number):
        return resolve_pull_request(evidence, candidates=(PullRequestResolutionCandidate(
            repository=evidence.repository, pull_request_number=pr_number,
            head_sha=evidence.tested_sha, state=PullRequestState.OPEN, evidence_source="offline-control",
        ),))
    return evidence, resolve(42), resolve(43)


def test_coherent_same_repo_sha_at_distinct_pr_needs_its_own_projection():
    evidence, first, second = inputs()
    wrong = render_comment_projection(evidence, first)
    fresh = render_comment_projection(evidence, second)
    # The managed build identity and user-facing body are unaffected.
    assert wrong.rendered_body == fresh.rendered_body
    assert wrong.stable_marker == fresh.stable_marker
    refused = plan_publication(evidence, second, wrong, comments_complete=True, comments=())
    assert refused.action is PublicationAction.MANUAL_REVIEW
    assert refused.reason_codes == ("publication.projection-evidence-mismatch",)

    allowed = plan_publication(evidence, second, fresh, comments_complete=True, comments=())
    assert (allowed.action, allowed.pull_request_number) == (PublicationAction.CREATE, 43)
    assert allowed.execution_authorized is False
    assert allowed.side_effects_performed is False


def test_legacy_projection_display_still_constructs_but_cannot_plan_a_write():
    evidence, first, _ = inputs()
    reported = render_comment_projection(evidence, first)
    legacy_input = {
        f.name: getattr(reported, f.name) for f in fields(reported)
        if f.init and f.name != "pull_request_number"
    }
    legacy = CloudBuildCommentProjection(**legacy_input)
    assert legacy.rendered_body == reported.rendered_body
    assert json.loads(serialize_projection(legacy)) == json.loads(serialize_projection(reported))

    refused = plan_publication(evidence, first, legacy, comments_complete=True, comments=())
    assert refused.action is PublicationAction.MANUAL_REVIEW
    assert refused.reason_codes == ("publication.projection-evidence-mismatch",)
    assert refused.execution_authorized is False
