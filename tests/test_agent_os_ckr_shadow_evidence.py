"""Offline fixture tests. The fixture readers are not deployment authorities."""
import hashlib
import io
import struct
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
# SHA-256 of compact UTF-8 [42,80,2,90,3,<checkout SHA>,"suite::fixture::named"].
EXECUTION_ID = "b7303d378a206b9d2bb0dccfaa83293b8bab758f9ca22b55e5b00cc866732e86"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_for(member, data):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(zipfile.ZipInfo(member), data)
    return stream.getvalue()


def with_archive_xml(evidence, xml, *, archive=None):
    """Bind replacement ZIP and member bytes to both independent digest surfaces."""
    if archive is None:
        archive = archive_for(evidence.output.case.member, xml)
    archive_sha = digest(archive)
    return replace(
        evidence, archive=archive,
        artifact={**evidence.artifact, "digest": "sha256:" + archive_sha},
        output=replace(evidence.output, archive_sha256=archive_sha,
                       member_sha256=digest(xml)),
    )


def forbid_reader(message):
    def unexpected(*_):
        pytest.fail(message)
    return unexpected


def fixture(*, xml=XML, **case_updates):
    case = replace(FrozenCase(REPO, 42, TASK, 4054, 71, "a" * 40, "b" * 40, 80, 2, 90, 3, 100,
                               "junit.xml", "suite::fixture::named", START, NOW), **case_updates)
    task = TaskEvidence(TASK, REPO)
    record = ApplicabilityRecord("LL-12", REV, (MECHANISM,),
                                 (InvariantRef(BOUNDARY, "production-boundary"),),
                                 (ApplicabilityCondition(MECHANISM, BOUNDARY),), (),
                                 "fixture-reviewer", f"https://github.com/{REPO}/pull/71", "reviewed")
    lesson = ShadowLessonState("LL-12", REV, "fixture", False, True, "current")
    policy = ShadowPolicy("fixture-v1", frozenset({(MECHANISM, BOUNDARY)}),
                          "fixture-issuer", "fixture-reviewer")
    run = dict(id=case.run_id, path=VALIDATION_WORKFLOW_PATH, head_sha=case.run_head_sha,
               status="completed", repository=dict(id=case.repository_id, full_name=REPO),
               event="pull_request", pull_requests=[dict(number=case.pr_number)], run_attempt=case.attempt)
    job = dict(id=case.job_id, run_id=case.run_id, run_attempt=case.attempt, head_sha=case.run_head_sha,
               name=AGGREGATE_STEP_NAME, status="completed", conclusion="success",
               completed_at=FINISH.isoformat(), steps=[dict(name=AGGREGATE_STEP_NAME,
               number=case.step_number, status="completed", conclusion="success")])
    archive = archive_for(case.member, xml)
    artifact = dict(id=case.artifact_id, expired=False, digest="sha256:" + digest(archive),
                    workflow_run=dict(id=case.run_id, repository_id=case.repository_id,
                                      head_sha=case.run_head_sha))
    output = VerifiedJobOutput(case, digest(archive), digest(xml))
    evidence = CollectedExecution(run, job, artifact, archive, output)
    review = ReviewedAttestation(output, record.lesson_id, REV, annotation_digest(record), policy.revision,
                                 policy.issuer, policy.reviewer, MECHANISM, BOUNDARY,
                                 NOW - timedelta(hours=1), NOW + timedelta(hours=1))
    return case, task, record, lesson, policy, evidence, review


def evaluate(*, changes=None, evidence_change=None, review_change=None, reviews=None,
             scenario=None, **kwargs):
    case, task, record, lesson, policy, evidence, review = fixture() if scenario is None else scenario
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


def assert_review_blocked(result, reason):
    assert_blocked(result, reason)
    assert (result.execution_id, result.job_conclusion) == (EXECUTION_ID, "success")


def test_confirmed_execution_and_independent_attestation_reach_pr2():
    result = evaluate()
    assert (result.status, result.reason) == ("qualified", "reviewed-observation")
    assert result.match is not None
    assert result.match.matched
    assert result.execution_id == EXECUTION_ID
    assert result.job_conclusion == "success"
    assert result == evaluate()


def test_ci_success_is_not_a_mechanism_attestation():
    result = evaluate(reviews=lambda _: ())
    assert_review_blocked(result, "authenticated-attestation-unavailable")


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
    assert_blocked(evaluate(changes=lambda c, *_: {"case": replace(c, **{field: value})},
                            read_review=forbid_reader("invalid case reached review")), reason)


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


@pytest.mark.parametrize("pull_requests", [
    [], [{"number": True}], [{"number": 71.0}], [{"number": "71"}],
])
def test_pr_binding_requires_one_strict_integer_before_review(pull_requests):
    def change(e):
        return replace(e, run={**e.run, "pull_requests": pull_requests})
    assert_blocked(evaluate(evidence_change=change,
                            read_review=forbid_reader("invalid PR binding reached review")),
                   "pr-binding-missing-or-ambiguous")


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
    assert_blocked(evaluate(evidence_change=lambda e: with_archive_xml(e, xml)), reason)


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
    assert_review_blocked(evaluate(review_change=lambda r: replace(r, **{field: value})), reason)


def test_duplicate_and_conflicting_reviews():
    assert evaluate(reviews=lambda r: (r, r)) == evaluate()
    for reverse in (False, True):
        assert_review_blocked(evaluate(reviews=lambda r: (
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
    scenario = (case, task, record, lesson, policy, evidence, review)
    duplicate = evaluate(
        scenario=scenario, changes=lambda *_: {"case": newer},
        evidence_change=lambda _: replace(
            evidence, output=output, artifact={**evidence.artifact, "id": newer.artifact_id},
        ),
        review_change=lambda _: replace(review, output=output),
    )
    assert duplicate == evaluate(scenario=scenario)


def test_multisuite_report_is_outside_first_slice():
    def change(e):
        xml = b"<testsuites>" + XML + XML.replace(b'name="suite"', b'name="other"') + b"</testsuites>"
        return with_archive_xml(e, xml)
    assert_blocked(evaluate(evidence_change=change), "junit-contradiction")


def evaluate_coherent_fixture(**case_updates):
    case, task, record, lesson, policy, evidence, review = fixture(**case_updates)
    return evaluate_shadow_case(case, task, record, lesson, policy=policy, as_of=NOW,
                                collect=lambda _: evidence, read_review=lambda *_: (review,))


@pytest.mark.parametrize("updates", [
    {"repository_id": 43}, {"run_id": 81}, {"attempt": 3}, {"job_id": 91},
    {"step_number": 4}, {"checkout_sha": "c" * 40},
    {"reporter_test_id": "suite::fixture::alternate", "xml": XML.replace(b'"named"', b'"alternate"')},
])
def test_distinct_bound_executions_cannot_share_observation_identity(updates):
    # Vary one verified identity dimension at a time, rather than making the
    # frozen case disagree with its synthetic provider source.
    first = evaluate()
    other = evaluate_coherent_fixture(**updates)
    assert first.status == other.status == "qualified"
    assert first.execution_id != other.execution_id


@pytest.mark.parametrize("member", ["junit.txt", "junit.XML", "x"])
def test_non_xml_member_rejected_even_when_present_and_digest_bound(member):
    assert_blocked(evaluate_coherent_fixture(member=member), "junit-member-unavailable")


def test_missing_xml_member_reports_unavailable_before_archive_read():
    def change(evidence):
        archive = archive_for("unrelated.xml", XML)
        return replace(evidence, archive=archive,
                       artifact={**evidence.artifact, "digest": "sha256:" + digest(archive)},
                       output=replace(evidence.output, archive_sha256=digest(archive)))

    assert_blocked(evaluate(evidence_change=change), "junit-member-unavailable")


@pytest.mark.parametrize("task", [
    type("DerivedTask", (TaskEvidence,), {})(TASK, REPO),
    TaskEvidence(f"https://github.com/{REPO}/issues/4055", REPO),
])
def test_subject_type_and_exact_task_binding_precede_reader_calls(task):
    unexpected = forbid_reader("invalid task accessed a reader")
    assert_blocked(evaluate(task=task, collect=unexpected, read_review=unexpected),
                   "task-binding-mismatch")


def test_review_reader_requires_verified_output_lesson_and_revision():
    _, _, _, _, _, evidence, review = fixture()
    received = []

    def exact_receipt_reader(output, lesson_id, revision):
        received.append((output, lesson_id, revision))
        return (review,) if (output, lesson_id, revision) == (evidence.output, "LL-12", REV) else ()

    assert evaluate(read_review=exact_receipt_reader).status == "qualified"
    assert received == [(evidence.output, "LL-12", REV)]


@pytest.mark.parametrize("field,value", [
    ("lesson_id", "LL-13"), ("source_revision", "2026-11-19T12:00:00.000Z"),
])
def test_review_reader_receives_current_frozen_lesson_binding(field, value):
    case, task, record, lesson, policy, evidence, _ = fixture()
    record = replace(record, **{field: value})
    lesson = replace(lesson, **{field: value})
    received = []

    def reader(output, lesson_id, revision):
        received.append((output, lesson_id, revision))
        return ()  # No matching independent review for the new frozen binding.

    result = evaluate_shadow_case(case, task, record, lesson, policy=policy, as_of=NOW,
                                  collect=lambda _: evidence, read_review=reader)
    assert_review_blocked(result, "authenticated-attestation-unavailable")
    assert received == [(evidence.output, record.lesson_id, record.source_revision)]


def test_alternate_xml_encoding_does_not_qualify_a_well_formed_report():
    # BOM-less UTF-16LE can be auto-detected by XML parsers; its zero bytes
    # must not be silently accepted as UTF-8 JUnit.
    xml = XML.decode("ascii").encode("utf-16le")
    assert_blocked(evaluate_coherent_fixture(xml=xml), "execution-evidence-malformed")


def test_review_annotation_digest_matches_frozen_canonical_record():
    # An independently serialized compact, sorted-key UTF-8 fixture. A reader
    # must not derive its expected digest using the implementation under test.
    reference_digest = "7e8bc3258aefc8aa3ee5e0b305d29b1fbb84d7c9d4da78c7481028ffee17cd8e"
    assert evaluate(review_change=lambda r: replace(r, annotation_sha256=reference_digest)).status == "qualified"


def test_duplicate_step_number_is_ambiguous_even_when_only_one_name_matches():
    def duplicated(evidence):
        original = evidence.job["steps"][0]
        job = {**evidence.job, "steps": [original, {**original, "name": "Unrelated step"}]}
        return replace(evidence, job=job)

    assert_blocked(evaluate(evidence_change=duplicated), "aggregate-step-mismatch")


def test_aggregate_step_binds_among_distinct_provider_steps():
    def multistep(evidence):
        aggregate = evidence.job["steps"][0]
        steps = [
            {**aggregate, "name": "Check out source", "number": 2},
            aggregate,
            {**aggregate, "name": "Upload evidence", "number": 4},
        ]
        return replace(evidence, job={**evidence.job, "steps": steps})

    assert evaluate(evidence_change=multistep) == evaluate()


@pytest.mark.parametrize("invalid_number", ["3", 3.0])
def test_noninteger_aggregate_number_cannot_borrow_unrelated_integer_step(invalid_number):
    def malformed(evidence):
        original = evidence.job["steps"][0]
        steps = [{**original, "number": invalid_number}, {**original, "name": "Unrelated step"}]
        return replace(evidence, job={**evidence.job, "steps": steps})

    assert_blocked(evaluate(evidence_change=malformed), "aggregate-step-mismatch")


def test_corrupted_compression_fails_closed_before_review_lookup():
    # Keep the ZIP directory recognizable; only the ordinary member stream is
    # damaged. A matching outer digest identifies bytes, not ZIP integrity.
    def corrupted(evidence):
        member = evidence.output.case.member
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member, XML)
        contents = bytearray(stream.getvalue())
        # Locate the payload using header metadata, including optional fields.
        with zipfile.ZipFile(io.BytesIO(contents)) as z:
            header = z.getinfo(member).header_offset
        filename_len, extra_len = struct.unpack_from("<HH", contents, header + 26)
        contents[header + 30 + filename_len + extra_len] = 0xFF
        return with_archive_xml(evidence, XML, archive=bytes(contents))

    assert_blocked(evaluate(evidence_change=corrupted,
                            read_review=forbid_reader("corrupted evidence was offered for review")),
                   "execution-evidence-malformed")


@pytest.mark.parametrize("changes", [
    {"attempt": 2.0},
    {"repository_id": 42.0},
    {"not_before": START.astimezone(timezone(timedelta(hours=1)))},
])
def test_issued_case_requires_exact_field_types_and_canonical_utc(changes):
    def malformed(evidence):
        output = replace(evidence.output, case=replace(evidence.output.case, **changes))
        return replace(evidence, output=output)

    assert_blocked(evaluate(evidence_change=malformed), "verified-job-output-subject-mismatch")


def test_reviewed_output_does_not_inherit_loose_case_equality():
    def malformed(review):
        output = replace(review.output, case=replace(review.output.case, attempt=2.0))
        return replace(review, output=output)

    assert_blocked(evaluate(review_change=malformed), "attestation-subject-mismatch")

    # An earlier valid entry must not hide a subsequent malformed entry that
    # compares equal under ordinary dataclass equality.
    assert_review_blocked(evaluate(reviews=lambda r: (r, malformed(r))),
                          "attestation-subject-mismatch")


@pytest.mark.parametrize("before,cutoff,reviewed_at", [
    (FINISH, NOW, FINISH), (START, FINISH, NOW), (FINISH, FINISH, FINISH),
])
def test_inclusive_execution_and_review_boundaries(before, cutoff, reviewed_at):
    case, task, record, lesson, policy, evidence, review = fixture(not_before=before, cutoff=cutoff)
    assert evaluate_shadow_case(
        case, task, record, lesson, policy=policy, as_of=NOW,
        collect=lambda pinned: evidence if pinned == case else None,
        read_review=lambda *_: (replace(review, reviewed_at=reviewed_at),),
    ).status == "qualified"


def test_noncanonical_utc_and_inverted_windows_fail_before_reading():
    unexpected = forbid_reader("invalid timing accessed a reader")
    offset = timezone(timedelta(hours=1))
    for clock in (NOW.replace(tzinfo=None), NOW.astimezone(offset)):
        result = evaluate(as_of=clock, collect=unexpected, read_review=unexpected)
        assert_blocked(result, "case-incomplete")
        assert (result.execution_id, result.job_conclusion) == (None, None)
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, *_: {
        "case": replace(c, not_before=NOW, cutoff=FINISH),
    }), "case-window-invalid")
    assert_review_blocked(evaluate(review_change=lambda r: replace(
        r, reviewed_at=r.reviewed_at.astimezone(offset),
    )), "attestation-stale-or-future")


@pytest.mark.parametrize("field,value", [
    ("attempt", 0), ("attempt", True), ("checkout_sha", "A" * 40),
    ("job_id", "90"), ("member", "a" * 509 + ".xml"),
])
def test_malformed_case_identity_and_bounds_stop_before_reading(field, value):
    unexpected = forbid_reader("invalid case accessed a reader")
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, *_: {
        "case": replace(c, **{field: value}),
    }), "case-incomplete")


def test_first_attempt_and_longest_supported_member_name_succeed():
    assert evaluate_coherent_fixture(attempt=1, member="a" * 508 + ".xml").status == "qualified"


def test_frozen_case_and_reviewed_lesson_require_exact_models():
    unexpected = forbid_reader("invalid subject accessed a reader")
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, *_: {
        "case": type("DerivedCase", (FrozenCase,), {})(**asdict(c)),
    }), "task-binding-mismatch")
    assert_blocked(evaluate(record=None, collect=unexpected), "lesson-binding-missing")
    assert_blocked(evaluate(lesson=None, collect=unexpected), "lesson-binding-missing")
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, t, r, l, p: {
        "record": replace(r, review_status="pending"),
    }), "lesson-not-eligible")


@pytest.mark.parametrize("changes,reason", [
    ({"revision": ""}, "policy-or-vocabulary-unapproved"),
    ({"revision": 12}, "policy-or-vocabulary-unapproved"),
    ({"approved_pairs": {(MECHANISM, BOUNDARY)}}, "policy-or-vocabulary-unapproved"),
    ({"issuer": " "}, "independent-authority-unavailable"),
])
def test_invalid_policy_never_reaches_the_provider(changes, reason):
    unexpected = forbid_reader("invalid policy accessed a reader")
    assert_blocked(evaluate(collect=unexpected, changes=lambda c, t, r, l, p: {
        "policy": replace(p, **changes),
    }), reason)


def test_review_read_failure_retains_execution_identity_and_opaque_error():
    def unavailable(*_):
        raise OSError("private-reader-detail")

    result = evaluate(read_review=unavailable)
    assert_review_blocked(result, "review-read-failed")
    assert "private-reader-detail" not in repr(result)


def test_review_batch_bound_includes_16_excludes_17_records():
    assert evaluate(reviews=lambda r: (r,) * 16) == evaluate()
    assert_review_blocked(evaluate(reviews=lambda r: (r,) * 17),
                          "authenticated-attestation-unavailable")


def test_invalid_pair_spelling_is_not_repaired_by_trusted_policy():
    malformed = "not a mechanism identifier"
    result = evaluate(changes=lambda c, t, r, l, p: {
        "policy": replace(p, approved_pairs=frozenset({(malformed, BOUNDARY)})),
    }, review_change=lambda r: replace(r, mechanism=malformed))
    assert_review_blocked(result, "observation-invalid")


def test_supported_failure_execution_is_distinct_from_mechanism_outcome():
    def failed(e):
        j = {**e.job, "conclusion": "failure",
             "steps": [{**e.job["steps"][0], "conclusion": "failure"}]}
        return replace(e, job=j)

    result = evaluate(evidence_change=failed)
    assert (result.status, result.job_conclusion, result.execution_id) == (
        "qualified", "failure", EXECUTION_ID,
    )


def test_non_byte_archive_rejected_before_review():
    assert_blocked(evaluate(evidence_change=lambda e: replace(e, archive=bytearray(e.archive))),
                   "archive-unavailable-or-oversized")


def test_raw_archive_byte_limit_is_inclusive(monkeypatch):
    # Exercise the same inclusive pre-read budget with a small actual ZIP so
    # every independent mutation run need not allocate a 64 MB artifact.
    limit = len(fixture()[-2].archive)
    setting = "scripts.agent_os_ckr_shadow_evidence.MAX_ARCHIVE_BYTES"
    monkeypatch.setattr(setting, limit)
    assert evaluate().status == "qualified"
    monkeypatch.setattr(setting, limit - 1)
    assert_blocked(evaluate(), "archive-unavailable-or-oversized")


def test_policy_does_not_coerce_alternate_identifier_types():
    # Exact string names are part of the reviewed vocabulary contract, even
    # when an in-process value would compare equal to the approved name.
    alternate = type("DerivedName", (str,), {})
    for field, value in (("mechanism", MECHANISM), ("boundary", BOUNDARY)):
        assert_review_blocked(evaluate(review_change=lambda r: replace(
            r, **{field: alternate(value)},
        )), "mechanism-boundary-unapproved")


@pytest.mark.parametrize("size", [8_000_000, 8_000_001])
def test_junit_member_size_limit_is_inclusive(size):
    def padded(e):
        xml = XML + b" " * (size - len(XML))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(e.output.case.member, xml)
        archive = stream.getvalue()
        return with_archive_xml(e, xml, archive=archive)

    baseline_review = fixture()[-1]
    result = evaluate(evidence_change=padded, read_review=lambda output, lesson_id, revision: (
        replace(baseline_review, output=output),
    ))
    if size == 8_000_000:
        assert result.status == "qualified"
    else:
        assert_blocked(result, "junit-member-oversized")
