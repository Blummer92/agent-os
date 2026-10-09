"""Regression tests for the fixed Ready-for-Review admission consumer (#3446)."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels import ready_admission_actions as ra
from scripts.agent_os_issue_labels.ready_for_review_admission import (
    evaluate_provisional_ready_reconciliation,
)

REPO = "Blummer92/agent-os"
HEAD = "a" * 40
BODY = "Refs #3463. Distinct from #3446.\n"
PR = 3481


def transport(**overrides):
    value = {
        "status": "accepted",
        "reason": ra.READY_ADMISSION_REASON,
        "repository": REPO,
        "issue_number": 3446,
        "comment_id": 9001,
        "logical_trigger_id_or_none": "issue-comment-trigger:" + "1" * 64,
        "ready_admission_pr_number_or_none": PR,
        "ready_admission_head_sha_or_none": HEAD,
        "ready_admission_body_sha256_or_none": ra.body_revision(BODY),
    }
    value.update(overrides)
    return value


def snapshot(**overrides):
    value = ra.PullRequestReadySnapshot(
        repository=REPO, pr_number=PR, state="open", draft=True, merged=False, head_sha=HEAD,
        title="#3463: routing", body=BODY, requested_changes=False, blocking_unresolved=0,
        focused_status="success", aggregate_status="skipped", validation_head_sha=HEAD)
    return replace(value, **overrides)


class Provider:
    def __init__(self, snap=None, error=None):
        self.snap, self.error, self.calls = snap, error, 0

    def read_pull_request(self, repository, pr_number):
        self.calls += 1
        if self.error:
            raise self.error
        return self.snap


def run(t=None, snap=None, error=None):
    return ra.evaluate_ready_admission(transport() if t is None else t, repository=REPO,
                                       provider=Provider(snap or snapshot(), error))


def assert_non_authorizing(receipt):
    for flag in ("ready_for_review_authorized", "merge_authorized", "issue_closure_authorized",
                 "workflow_authorized", "protected_setting_authorized", "production_authorized",
                 "external_system_write_authorized", "side_effects_performed"):
        assert receipt[flag] is False


def test_eligible_provisional_ready_admission_is_bound_and_reversible():
    receipt = run()
    assert receipt["transition_admissible"] is True
    assert receipt["provisional_ready"] is True
    assert receipt["rollback_to_draft_required"] is True
    assert receipt["reason_codes"] == ["provisional-ready-aggregate-trigger-admitted"]
    assert receipt["expected_head_sha"] == receipt["observed_head_sha"] == HEAD
    assert receipt["observed_body_sha256"] == ra.body_revision(BODY)
    assert_non_authorizing(receipt)
    json.dumps(receipt)


def test_exact_head_green_aggregate_is_ordinary_ready():
    receipt = run(snap=snapshot(aggregate_status="success"))
    assert receipt["transition_admissible"] is True
    assert receipt["provisional_ready"] is False
    assert receipt["rollback_to_draft_required"] is False


def test_stale_head_refused():
    receipt = run(snap=snapshot(head_sha="b" * 40, validation_head_sha="b" * 40))
    assert receipt["transition_admissible"] is False
    assert "stale-head" in receipt["reason_codes"]


def test_stale_body_refused():
    receipt = run(snap=snapshot(body=BODY + "edited"))
    assert receipt["transition_admissible"] is False
    assert "stale-body-revision" in receipt["reason_codes"]


@pytest.mark.parametrize("body", ["Closes #2880", "fixes #1", "Resolves https://github.com/Blummer92/agent-os/issues/7"])
def test_unauthorized_closing_reference_refused(body):
    receipt = run(t=transport(ready_admission_body_sha256_or_none=ra.body_revision(body)), snap=snapshot(body=body))
    assert receipt["transition_admissible"] is False
    assert "unauthorized-closing-reference" in receipt["reason_codes"]


def test_unnormalizable_closing_reference_fails_closed():
    body = "Resolves Blummer92/agent-os#7"
    receipt = run(t=transport(ready_admission_body_sha256_or_none=ra.body_revision(body)), snap=snapshot(body=body))
    assert receipt["transition_admissible"] is False
    assert receipt["reason_codes"] == ["pr-evidence-invalid"]


def test_review_blockers_refused():
    assert "requested-changes-unresolved" in run(snap=snapshot(requested_changes=True))["reason_codes"]
    assert "blocking-review-conversation-unresolved" in run(snap=snapshot(blocking_unresolved=2))["reason_codes"]


def test_failed_or_missing_validation_refused_and_manual_review_pr_stays_blocked():
    failed = run(snap=snapshot(focused_status="failure"))
    assert failed["transition_admissible"] is False
    assert "focused-validation-not-green" in failed["reason_codes"]
    failing_aggregate = run(snap=snapshot(aggregate_status="failure"))
    assert failing_aggregate["transition_admissible"] is False
    assert "authoritative-aggregate-not-green" in failing_aggregate["reason_codes"]


def test_already_ready_or_merged_pr_refused():
    assert "pr-not-draft" in run(snap=snapshot(draft=False))["reason_codes"]
    assert "pr-not-draft" in run(snap=snapshot(merged=True, state="closed"))["reason_codes"]


def test_wrong_repository_or_pr_identity_refused():
    assert "repository-mismatch" in run(snap=snapshot(repository="Blummer92/other"))["reason_codes"]
    assert "pr-identity-mismatch" in run(snap=snapshot(pr_number=PR + 1))["reason_codes"]
    other = ra.evaluate_ready_admission(transport(repository="Blummer92/other"), repository=REPO,
                                        provider=Provider(snapshot()))
    assert other["transition_admissible"] is False
    assert other["reason_codes"] == ["repository-mismatch"]


@pytest.mark.parametrize("bad", [
    None, [], "x", {},
    transport(status="blocked"),
    transport(reason="accepted-envelope"),
    transport(ready_admission_pr_number_or_none=True),
    transport(ready_admission_pr_number_or_none=0),
    transport(ready_admission_head_sha_or_none="A" * 40),
    transport(ready_admission_head_sha_or_none="a" * 39),
    transport(ready_admission_body_sha256_or_none="z" * 64),
    transport(logical_trigger_id_or_none=None),
])
def test_forged_or_malformed_transport_never_reads_github(bad):
    provider = Provider(snapshot())
    receipt = ra.evaluate_ready_admission(bad, repository=REPO, provider=provider)
    assert receipt["transition_admissible"] is False
    assert provider.calls == 0
    assert_non_authorizing(receipt)


def test_unavailable_or_invalid_evidence_fails_closed():
    assert run(error=RuntimeError("boom"))["reason_codes"] == ["pr-evidence-unavailable"]
    assert "validation-status-uninterpretable" in run(snap=snapshot(aggregate_status="weird"))["reason_codes"]


# ---- host-side consumption gate -------------------------------------------------

TRIGGER_ID = transport()["logical_trigger_id_or_none"]


def verify(receipt, **overrides):
    kwargs = dict(repository=REPO, pr_number=PR, expected_trigger_id=TRIGGER_ID,
                  current_head_sha=HEAD, current_body=BODY)
    kwargs.update(overrides)
    return ra.verify_ready_admission_receipt(receipt, **kwargs)


def test_host_accepts_only_fresh_matching_admitting_receipt():
    assert verify(run()) == (True, ())


def test_host_rejects_missing_forged_stale_duplicate_and_non_admitting_receipts():
    receipt = run()
    assert verify(None) == (False, ("receipt-missing",))
    forged = dict(receipt, transition_admissible=True, reason_codes=["x"])
    assert "receipt-forged" in verify(forged)[1]
    authority = dict(receipt, merge_authorized=True)
    assert "receipt-malformed" in verify(authority)[1]
    assert "receipt-stale-head" in verify(receipt, current_head_sha="b" * 40)[1]
    assert "receipt-stale-body" in verify(receipt, current_body=BODY + "edit")[1]
    assert "receipt-duplicate" in verify(receipt, consumed_receipt_ids=frozenset({receipt["receipt_id"]}))[1]
    assert "receipt-identity-mismatch" in verify(receipt, pr_number=PR + 1)[1]
    assert "receipt-trigger-mismatch" in verify(receipt, expected_trigger_id="other")[1]
    refused = run(snap=snapshot(body=BODY + "edited"))
    assert verify(refused, current_body=BODY + "edited")[0] is False


def test_provisional_ready_failure_requires_rollback_to_draft():
    failed = evaluate_provisional_ready_reconciliation(
        repository=REPO, pr_number=PR, pr_lifecycle_state="ready", expected_head_sha=HEAD,
        observed_head_sha=HEAD, validation_head_sha=HEAD, aggregate_status="failure")
    assert failed.rollback_to_draft_required is True
    unavailable = evaluate_provisional_ready_reconciliation(
        repository=REPO, pr_number=PR, pr_lifecycle_state="ready", expected_head_sha=HEAD,
        observed_head_sha=HEAD, validation_head_sha=HEAD, aggregate_status="pending")
    assert unavailable.rollback_to_draft_required is True


def test_batch_continues_past_independently_blocked_item():
    snaps = {3411: snapshot(pr_number=3411, focused_status="failure"),
             3449: snapshot(pr_number=3449, body="Closes #2880", title="x"),
             3481: snapshot()}
    bodies = {3449: "Closes #2880"}

    def decide(request):
        number = request["pr_number"]
        if number == 9999:
            raise RuntimeError("unexpected")
        body = bodies.get(number, BODY)
        t = transport(ready_admission_pr_number_or_none=number,
                      ready_admission_body_sha256_or_none=ra.body_revision(body))
        receipt = ra.evaluate_ready_admission(t, repository=REPO, provider=Provider(snaps[number]))
        return receipt["transition_admissible"], tuple(receipt["reason_codes"])

    result = ra.run_ready_batch(
        [{"pr_number": 3411}, {"pr_number": 3449}, {"pr_number": 9999}, {"pr_number": 3481}], decide)
    assert [item["disposition"] for item in result] == [
        "blocked-item-local", "blocked-item-local", "blocked-item-local", "ready-eligible"]
    assert result[1]["reason_codes"] == ["unauthorized-closing-reference", "draft-final-candidate-validation-not-proven"] \
        or "unauthorized-closing-reference" in result[1]["reason_codes"]


def test_repeated_identical_request_yields_identical_receipt_id():
    assert run()["receipt_id"] == run()["receipt_id"]


def test_main_writes_receipt_and_fails_closed_without_github_client(tmp_path, monkeypatch):
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    source, out = tmp_path / "transport.json", tmp_path / "receipt.json"
    source.write_text(json.dumps(transport()), encoding="utf-8")
    assert ra.main(["--transport", str(source), "--repository", REPO, "--output", str(out)]) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["transition_admissible"] is False
    assert receipt["reason_codes"] == ["pr-evidence-unavailable"]


def test_pygithub_provider_maps_evidence_read_only():
    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    commit = Obj(
        get_check_runs=lambda: [Obj(name=ra.FOCUSED_CHECK_NAME, status="completed", conclusion="success"),
                                Obj(name=ra.AGGREGATE_JOB_NAME, status="completed", conclusion="skipped")],
        get_statuses=lambda: [])
    pr = Obj(head=Obj(sha=HEAD), draft=True, state="open", merged=False, title="t", body=BODY,
             get_reviews=lambda: [Obj(state="CHANGES_REQUESTED", user=Obj(login="r"))])
    repo = Obj(get_pull=lambda n: pr, get_commit=lambda sha: commit)

    class Requester:
        def graphql_query(self, query, variables):
            assert "mutation" not in query
            return {}, {"data": {"repository": {"pullRequest": {"reviewThreads": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{"isResolved": False, "isOutdated": False}, {"isResolved": True, "isOutdated": False}]}}}}}

    client = Obj(get_repo=lambda name: repo, requester=Requester())
    snap = ra.PyGithubReadyAdmissionProvider(client).read_pull_request(REPO, PR)
    assert (snap.focused_status, snap.aggregate_status) == ("success", "skipped")
    assert snap.requested_changes is True and snap.blocking_unresolved == 1
    assert snap.validation_head_sha == HEAD
