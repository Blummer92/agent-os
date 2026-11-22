"""Offline fixture tests. The fixture readers are not deployment authorities."""
import hashlib
import io
import zipfile
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest

from agent_memory_context_manager.lesson_applicability import (
    ApplicabilityCondition, ApplicabilityRecord, InvariantRef, ShadowLessonState, TaskEvidence,
)
from scripts.agent_os_ckr_shadow_evidence import (
    CollectedExecution, FrozenCase, ReviewedAttestation, ShadowPolicy,
    VerifiedJobOutput, annotation_digest, evaluate_shadow_case,
)
from scripts.agent_os_ci_evidence_collector import AGGREGATE_STEP_NAME, VALIDATION_WORKFLOW_PATH

REPO = "Blummer92/agent-os"
TASK = f"https://github.com/{REPO}/issues/4054"
MECHANISM = "test-mechanism"
BOUNDARY = "test-boundary"
REV = "2026-11-18T12:00:00.000Z"
NOW = datetime(2026, 11, 22, 4, tzinfo=timezone.utc)
FINISH = NOW - timedelta(hours=2)
START = FINISH - timedelta(hours=1)
XML = b'<testsuite name="suite" tests="1" failures="0" errors="0" skipped="0"><testcase classname="fixture" name="named"/></testsuite>'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_for(member, data):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(zipfile.ZipInfo(member), data)
    return stream.getvalue()


def fixture():
    case = FrozenCase(REPO, 42, TASK, 4054, 71, "a" * 40, "b" * 40, 80, 2, 90, 3, 100,
                      "junit.xml", "suite::fixture::named", START, NOW)
    task = TaskEvidence(TASK, REPO)
    record = ApplicabilityRecord("LL-12", REV, (MECHANISM,),
                                 (InvariantRef(BOUNDARY, "production-boundary"),),
                                 (ApplicabilityCondition(MECHANISM, BOUNDARY),), (),
                                 "fixture-reviewer", f"https://github.com/{REPO}/pull/71", "reviewed")
    lesson = ShadowLessonState("LL-12", REV, "fixture", False, True, "current")
    policy = ShadowPolicy("fixture-v1", frozenset({(MECHANISM, BOUNDARY)}),
                          "fixture-issuer", "fixture-reviewer")
    run = dict(id=80, path=VALIDATION_WORKFLOW_PATH, head_sha=case.run_head_sha,
               status="completed", repository=dict(id=42, full_name=REPO),
               event="pull_request", pull_requests=[dict(number=71)], run_attempt=2)
    job = dict(id=90, run_id=80, run_attempt=2, head_sha=case.run_head_sha,
               name=AGGREGATE_STEP_NAME, status="completed", conclusion="success",
               completed_at=FINISH.isoformat(), steps=[dict(name=AGGREGATE_STEP_NAME,
               number=3, status="completed", conclusion="success")])
    archive = archive_for(case.member, XML)
    artifact = dict(id=100, expired=False, digest="sha256:" + digest(archive),
                    workflow_run=dict(id=80, repository_id=42, head_sha=case.run_head_sha))
    output = VerifiedJobOutput(case, digest(archive), digest(XML))
    evidence = CollectedExecution(run, job, artifact, archive, output)
    review = ReviewedAttestation(output, record.lesson_id, REV, annotation_digest(record), policy.revision,
                                 policy.issuer, policy.reviewer, MECHANISM, BOUNDARY,
                                 NOW - timedelta(hours=1), NOW + timedelta(hours=1))
    return case, task, record, lesson, policy, evidence, review


def evaluate(*, changes=None, evidence_change=None, review_change=None, reviews=None, **kwargs):
    case, task, record, lesson, policy, evidence, review = fixture()
    args = dict(case=case, task=task, record=record, lesson=lesson, policy=policy, as_of=NOW)
    if changes:
        args.update(changes(case, task, record, lesson, policy))
    args.update(kwargs)
    args.setdefault("collect", lambda _: evidence_change(evidence) if evidence_change else evidence)
    args.setdefault("read_review", lambda *_: reviews(review) if reviews else (
        review_change(review) if review_change else review,
    ))
    return evaluate_shadow_case(**args)


def assert_blocked(result, reason):
    assert (result.status, result.reason, result.match) == ("blocked", reason, None)


def test_confirmed_execution_and_independent_attestation_reach_pr2():
    result = evaluate()
    assert (result.status, result.reason) == ("qualified", "reviewed-observation")
    assert result.match is not None
    assert result.match.matched
    assert len(result.execution_id) == 64
    assert result.job_conclusion == "success"
    assert result == evaluate()


def test_ci_success_is_not_a_mechanism_attestation():
    result = evaluate(reviews=lambda _: ())
    assert_blocked(result, "authenticated-attestation-unavailable")
    assert result.execution_id is not None


def test_no_reader_no_acquisition_and_no_static_signal():
    assert_blocked(evaluate(collect=None), "authenticated-source-unavailable")
    assert_blocked(evaluate(read_review=None), "independent-authority-unavailable")
    assert_blocked(evaluate(
        changes=lambda c, t, r, l, p: {"task": replace(t, static_inferred_refs=("source.py",))},
        reviews=lambda _: (),
    ), "authenticated-attestation-unavailable")


@pytest.mark.parametrize("field,value,reason", [
    ("checkout_sha", "c" * 40, "verified-job-output-subject-mismatch"),
    ("run_head_sha", "c" * 40, "execution-evidence-malformed"),
    ("attempt", 3, "run-attempt-job-mismatch"),
    ("job_id", 91, "run-attempt-job-mismatch"),
    ("step_number", 4, "aggregate-step-mismatch"),
    ("artifact_id", 101, "artifact-binding-invalid"),
    ("repository_id", 43, "repository-mismatch"),
    ("pr_number", 72, "pr-binding-missing-or-ambiguous"),
    ("issue_number", 4055, "task-binding-mismatch"),
    ("reporter_test_id", "", "case-incomplete"),
])
def test_exact_case_binding(field, value, reason):
    assert_blocked(evaluate(changes=lambda c, *_: {"case": replace(c, **{field: value})}), reason)


@pytest.mark.parametrize("changes,reason", [
    ({"run": {"event": "workflow_dispatch"}}, "pr-binding-missing-or-ambiguous"),
    ({"run": {"pull_requests": [{"number": 71}, {"number": 72}]}}, "pr-binding-missing-or-ambiguous"),
    ({"job": {"steps": []}}, "aggregate-step-unavailable-or-ambiguous"),
    ({"run": {"run_attempt": 3}}, "run-attempt-job-mismatch"),
    ({"job": {"head_sha": "c" * 40}}, "run-attempt-job-mismatch"),
    ({"job": {"run_attempt": True}}, "provider-identity-malformed"),
    ({"job": {"completed_at": "2025-11-21T00:00:00Z"}}, "execution-outside-window"),
    ({"job": {"conclusion": "skipped"}}, "job-not-executed"),
    ({"artifact": {"expired": True}}, "artifact-binding-invalid"),
    ({"artifact": {"digest": None}}, "archive-digest-missing-or-mismatch"),
    ({"artifact": {"digest": "sha256:" + "0" * 64}}, "archive-digest-missing-or-mismatch"),
])
def test_provider_bindings(changes, reason):
    assert_blocked(evaluate(evidence_change=lambda e: replace(
        e, **{k: {**getattr(e, k), **v} for k, v in changes.items()},
    )), reason)


def test_source_json_and_name_only_artifact_join_do_not_qualify():
    assert_blocked(evaluate(evidence_change=asdict), "execution-evidence-unavailable")
    assert_blocked(evaluate(evidence_change=lambda e: replace(e, output=None)),
                   "authenticated-job-output-unavailable")
    assert_blocked(evaluate(evidence_change=lambda e: replace(
        e, output=replace(e.output, member_sha256="0" * 64),
    )), "member-digest-mismatch")
    assert_blocked(evaluate(reviews=lambda r: (asdict(r),)), "authenticated-attestation-unavailable")


@pytest.mark.parametrize("xml,reason", [
    (b"", "execution-evidence-malformed"),
    (XML.replace(b'name="named"', b'name="other"'), "named-test-not-confirmed"),
    (XML.replace(b"/>", b"><skipped/></testcase>"), "junit-contradiction"),
    (XML.replace(b'skipped="0"', b'skipped="1"').replace(b"/>", b"><skipped/></testcase>"),
     "named-test-not-confirmed"),
    (XML.replace(b'tests="1"', b'tests="2"'), "junit-contradiction"),
    (XML.replace(b'failures="0"', b'failures="1"').replace(b"/>", b"><failure/></testcase>"),
     "junit-contradiction"),
])
def test_only_executed_consistent_named_junit(xml, reason):
    def change(e):
        archive = archive_for(e.output.case.member, xml)
        return replace(e, archive=archive, artifact={**e.artifact, "digest": "sha256:" + digest(archive)},
                       output=replace(e.output, archive_sha256=digest(archive), member_sha256=digest(xml)))
    assert_blocked(evaluate(evidence_change=change), reason)


@pytest.mark.parametrize("field,value,reason", [
    ("issuer", "unapproved-issuer", "attestation-authority-mismatch"),
    ("reviewer", "unapproved-reviewer", "attestation-authority-mismatch"),
    ("mechanism", "unknown-mechanism", "mechanism-boundary-unapproved"),
    ("boundary", "unknown-boundary", "mechanism-boundary-unapproved"),
    ("expires_at", NOW, "attestation-stale-or-future"),
    ("reviewed_at", NOW + timedelta(minutes=1), "attestation-stale-or-future"),
    ("policy_revision", "old-map", "attestation-subject-mismatch"),
    ("annotation_sha256", "0" * 64, "attestation-subject-mismatch"),
])
def test_independently_approved_binding(field, value, reason):
    assert_blocked(evaluate(review_change=lambda r: replace(r, **{field: value})), reason)


def test_duplicate_and_conflicting_reviews():
    assert evaluate(reviews=lambda r: (r, r)) == evaluate()
    for reverse in (False, True):
        assert_blocked(evaluate(reviews=lambda r: (
            r, replace(r, boundary="other"),
        )[::(-1 if reverse else 1)]), "conflicting-attestations")


def test_changed_lesson_revision_and_unresolved_policy():
    assert_blocked(evaluate(changes=lambda c, t, r, l, p: {
        "lesson": replace(l, source_revision="2026-11-19T12:00:00.000Z"),
    }), "lesson-revision-mismatch")
    assert_blocked(evaluate(policy=None), "policy-or-vocabulary-unapproved")
    assert_blocked(evaluate(changes=lambda c, t, r, l, p: {
        "policy": replace(p, approved_pairs=frozenset()),
    }), "policy-or-vocabulary-unapproved")
    assert_blocked(evaluate(changes=lambda c, t, r, l, p: {
        "policy": replace(p, reviewer=p.issuer),
    }), "independent-authority-unavailable")


def test_an_edited_annotation_cannot_reuse_same_revision_review():
    assert_blocked(evaluate(changes=lambda c, t, r, l, p: {
        "record": replace(r, positive_conditions=(ApplicabilityCondition(MECHANISM),)),
    }), "attestation-subject-mismatch")


def test_archived_lesson_never_reaches_provider():
    def unexpected(_):
        pytest.fail("ineligible lesson accessed provider")
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, t, r, l, p: {
        "lesson": replace(l, archived=True),
    }), "lesson-not-eligible")


def test_source_failure_is_privacy_safe():
    def unavailable(_):
        raise OSError("secret-internal-location")
    result = evaluate(collect=unavailable)
    assert_blocked(result, "execution-read-failed")
    assert "secret" not in repr(result)


def test_repackaged_artifact_is_not_a_second_execution():
    case, task, record, lesson, policy, evidence, review = fixture()
    newer = replace(case, artifact_id=case.artifact_id + 1)
    output = replace(evidence.output, case=newer)
    duplicate = evaluate(
        changes=lambda *_: {"case": newer},
        evidence_change=lambda _: replace(
            evidence, output=output, artifact={**evidence.artifact, "id": newer.artifact_id},
        ),
        review_change=lambda _: replace(review, output=output),
    )
    assert duplicate == evaluate()


def test_multisuite_report_is_outside_first_slice():
    def change(e):
        xml = b"<testsuites>" + XML + XML.replace(b'name="suite"', b'name="other"') + b"</testsuites>"
        archive = archive_for(e.output.case.member, xml)
        return replace(e, archive=archive, artifact={**e.artifact, "digest": "sha256:" + digest(archive)},
                       output=replace(e.output, archive_sha256=digest(archive), member_sha256=digest(xml)))
    assert_blocked(evaluate(evidence_change=change), "junit-contradiction")
