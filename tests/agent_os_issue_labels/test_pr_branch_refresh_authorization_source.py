import hashlib
import json

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    RefreshAuthorization, RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    AUTHORIZATION_MARKER, RECEIPT_MARKER,
    RefreshAuthorizationCommentSnapshot, RefreshAuthorizationReceipt,
    RefreshAuthorizationSourceSnapshot, RefreshAuthorizationSourceStatus,
    _identity_digest_material,
    reacquire_refresh_authorization_source,
    serialize_refresh_authorization_comment, serialize_refresh_authorization_receipt,
)

REPO = "Blummer92/agent-os"
HEAD = "a" * 40
MAIN = "b" * 40


def auth(**overrides):
    values = dict(schema_version="1.0", repository=REPO, pr_number=1363,
        base_branch="main", expected_head_sha=HEAD, expected_main_sha=MAIN,
        allowed_changed_paths=("x.py",), forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True, label_write_authorized=False,
        owner_decision_reference="github-owner-decision:1363", state=RefreshAuthorizationState.AUTHORIZED)
    values.update(overrides)
    return RefreshAuthorization(**values)


def receipt(record=None, **overrides):
    record = record or auth()
    values = dict(schema_version="1.0", repository=REPO, pr_number=1363,
        authorization_id=record.authorization_id, admitted_head_sha=HEAD,
        admitted_main_sha=MAIN, mutation_attempted=True, mutation_succeeded=False,
        terminal_status="mutation-failed", reason_codes=("refresh.failed",))
    values.update(overrides)
    return RefreshAuthorizationReceipt(**values)


class Transport:
    def __init__(self, comments, *, complete=True, owner="Blummer92", owner_type="User"):
        self.calls = 0
        self.snapshot = RefreshAuthorizationSourceSnapshot(repository=REPO, pr_number=1363,
            owner_login=owner, owner_type=owner_type, comments_complete=complete,
            comments=tuple(comments))
    def read_refresh_authorization_source(self, repository, pr_number):
        self.calls += 1
        return self.snapshot


def comment(body, cid=1, author="Blummer92"):
    return RefreshAuthorizationCommentSnapshot(comment_id=cid, author_login=author,
        created_at=f"2026-09-03T18:00:{cid:02d}Z", body=body)


def read(comments, **kwargs):
    transport = Transport(comments, **kwargs)
    result = reacquire_refresh_authorization_source(transport=transport, repository=REPO, pr_number=1363)
    assert transport.calls == 1
    return result


def test_exact_owner_machine_record_is_current_and_deterministic():
    record = auth()
    body = serialize_refresh_authorization_comment(record)
    assert body.startswith(AUTHORIZATION_MARKER + "\n")
    assert body == serialize_refresh_authorization_comment(auth())
    result = read([comment(body)])
    assert result.status is RefreshAuthorizationSourceStatus.CURRENT
    assert result.records == (record,)
    assert result.side_effects_performed is False


def test_non_owner_marker_and_ordinary_owner_prose_cannot_authorize():
    body = serialize_refresh_authorization_comment(auth())
    assert read([comment(body, author="other")]).status is RefreshAuthorizationSourceStatus.BLOCKED
    assert read([comment("I authorize this refresh")]).status is RefreshAuthorizationSourceStatus.BLOCKED


def test_incomplete_source_and_unsupported_owner_fail_closed():
    body = serialize_refresh_authorization_comment(auth())
    assert read([comment(body)], complete=False).status is RefreshAuthorizationSourceStatus.NEEDS_DECISION
    assert read([comment(body)], owner_type="Organization").status is RefreshAuthorizationSourceStatus.NEEDS_DECISION


def test_tampered_authorization_identity_fails_closed():
    body = serialize_refresh_authorization_comment(auth()).replace("refresh-authorization:", "refresh-authorization:0")
    result = read([comment(body)])
    assert result.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("source.trusted-record-malformed",)


def test_repository_or_pr_rebinding_fails_closed():
    for record in (auth(repository="other/repo"), auth(pr_number=99)):
        result = read([comment(serialize_refresh_authorization_comment(record))])
        assert result.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION


def test_consumption_receipt_is_immutable_content_bound_and_blocks_reuse():
    record = auth()
    consumed = receipt(record)
    body = serialize_refresh_authorization_receipt(consumed)
    assert body.startswith(RECEIPT_MARKER + "\n")
    assert consumed.receipt_id == receipt(record).receipt_id
    result = read([comment(serialize_refresh_authorization_comment(record)), comment(body, cid=2)])
    assert result.status is RefreshAuthorizationSourceStatus.STALE
    assert result.records == ()
    assert result.receipts == (consumed,)


def test_non_consuming_receipt_does_not_consume_authorization():
    record = auth()
    preflight = receipt(record, mutation_attempted=False, mutation_succeeded=False,
        terminal_status="not-consumed", reason_codes=("preflight.blocked",))
    result = read([comment(serialize_refresh_authorization_comment(record)),
        comment(serialize_refresh_authorization_receipt(preflight), cid=2)])
    assert result.status is RefreshAuthorizationSourceStatus.CURRENT
    assert result.records == (record,)


def test_historical_noncurrent_records_can_coexist_with_one_current_record():
    historical = auth(state=RefreshAuthorizationState.SUPERSEDED)
    current = auth(owner_decision_reference="github-owner-decision:1363-v2")
    result = read([comment(serialize_refresh_authorization_comment(historical)),
        comment(serialize_refresh_authorization_comment(current), cid=2)])
    assert result.status is RefreshAuthorizationSourceStatus.CURRENT
    assert result.records == (current,)


def test_multiple_simultaneously_applicable_grants_fail_closed_without_timestamp_selection():
    first = auth(owner_decision_reference="decision:a")
    second = auth(owner_decision_reference="decision:b")
    result = read([comment(serialize_refresh_authorization_comment(first)),
        comment(serialize_refresh_authorization_comment(second), cid=2)])
    assert result.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == ("authorization.ambiguous",)


def test_expected_authorization_identity_selects_exact_record_not_newest_timestamp():
    first = auth(owner_decision_reference="decision:a")
    second = auth(owner_decision_reference="decision:b")
    transport = Transport([comment(serialize_refresh_authorization_comment(first)),
        comment(serialize_refresh_authorization_comment(second), cid=2)])
    result = reacquire_refresh_authorization_source(transport=transport, repository=REPO,
        pr_number=1363, expected_authorization_id=first.authorization_id)
    assert result.status is RefreshAuthorizationSourceStatus.CURRENT
    assert result.records == (first,)


def test_duplicate_comment_identity_and_malformed_trusted_record_fail_closed():
    body = serialize_refresh_authorization_comment(auth())
    duplicate = read([comment(body), comment(body)])
    assert duplicate.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION
    malformed = read([comment(AUTHORIZATION_MARKER + "\n{}")])
    assert malformed.status is RefreshAuthorizationSourceStatus.NEEDS_DECISION


def test_receipt_tamper_is_detected_and_receipt_never_grants_authority():
    consumed = receipt()
    values = consumed.to_dict()
    # `to_dict()` is the JSON-serialization surface, so it emits a list; the
    # parse path reconstructs the exact tuple field type before validation.
    values["reason_codes"] = tuple(values["reason_codes"])
    values["receipt_id"] = "refresh-authorization-receipt:" + "0" * 64
    with pytest.raises(ValueError, match="receipt_id does not match content"):
        RefreshAuthorizationReceipt(**values)
    assert consumed.side_effects_performed is False


def test_identity_digest_material_is_version_scoped_and_null_separated():
    payload = {"b": 2, "a": [1, "x"]}
    material = _identity_digest_material("refresh-authorization-receipt", payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert material == "refresh-authorization-receipt:v1\0" + canonical
    expected = hashlib.sha256(material.encode()).hexdigest()
    assert receipt().receipt_id == "refresh-authorization-receipt:" + hashlib.sha256(
        _identity_digest_material("refresh-authorization-receipt", receipt()._identity_payload()).encode()
    ).hexdigest()
    assert expected != hashlib.sha256(
        _identity_digest_material("refresh-authorization-receipt", {"a": [1, "x"], "b": 3}).encode()
    ).hexdigest()
