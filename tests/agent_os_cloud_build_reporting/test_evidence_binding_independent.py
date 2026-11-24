"""Cloud-only extraction of Gemini audit patch 04."""
from scripts.agent_os_cloud_build_reporting import (
    OverallResult, PublicationAction, PullRequestResolutionCandidate,
    PullRequestState, normalize_cloud_build_evidence, resolve_pull_request,
    render_comment_projection, plan_publication,
)


def evidence(repo='blummer92/agent-os', build='build-a'):
    return normalize_cloud_build_evidence(build_id=build, tested_sha='a' * 40,
        repository=repo, overall_result=OverallResult.SUCCESS, terminal=True,
        source_complete=True, failed_step='none', exit_code=0)


def resolution(e, pr=42):
    return resolve_pull_request(e, candidates=(PullRequestResolutionCandidate(
        repository=e.repository, pull_request_number=pr, head_sha=e.tested_sha,
        state=PullRequestState.OPEN, evidence_source='canonical-pr-readback'),))


def test_cloud_projection_from_different_build_is_refused():
    original = evidence()
    other = evidence(build='build-b')
    result = plan_publication(original, resolution(original),
        render_comment_projection(other, resolution(other)), comments_complete=True, comments=())
    assert result.action is PublicationAction.MANUAL_REVIEW


def test_cloud_resolution_from_other_repository_is_refused():
    original = evidence()
    other = evidence(repo='other/repo')
    foreign_resolution = resolution(other, 999)
    result = plan_publication(original, foreign_resolution,
        render_comment_projection(original, foreign_resolution), comments_complete=True, comments=())
    assert result.action is PublicationAction.MANUAL_REVIEW


def test_same_evidence_publication_still_plans_exact_pr():
    original = evidence()
    resolved = resolution(original)
    result = plan_publication(original, resolved, render_comment_projection(original, resolved),
        comments_complete=True, comments=())
    assert result.action is PublicationAction.CREATE
    assert result.pull_request_number == 42
    assert result.execution_authorized is False
