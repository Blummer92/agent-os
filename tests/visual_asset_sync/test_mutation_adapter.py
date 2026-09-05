from datetime import datetime, timedelta, timezone

import pytest

from visual_asset_sync.models import ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.mutation_adapter import (
    MutationAuthorization,
    MutationAuthorizationError,
    MutationExecutionError,
    build_mutation_actions,
    execute_mutation_actions,
    plan_digest,
    validate_plan_authorization,
)
from visual_asset_sync.notion_adapter import SUPPORTED_NOTION_VERSION


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
MAPPING = {"drive_file_id": "file_id", "approved_use": "Approved use"}


def _records():
    return (
        SourceAssetRecord(source_row="2", drive_file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz123456", approved_use="Slides"),
        SourceAssetRecord(source_row="3", drive_file_id="1ZyXwVuTsRqPoNmLkJiHgFeDcBa654321", approved_use="Worksheet"),
    )


def _entries():
    records = _records()
    return (
        ReconciliationEntry(
            source_row="2",
            result=ReconciliationResult.UPDATE_EXISTING,
            identity_key=records[0].drive_file_id,
            matched_page_ids=("page-1",),
        ),
        ReconciliationEntry(
            source_row="3",
            result=ReconciliationResult.CREATE_MISSING,
            identity_key=records[1].drive_file_id,
        ),
    )


def _authorization(entries=None, **changes):
    entries = entries or _entries()
    values = dict(
        data_source_id="da5cba48-50fd-4377-9790-8df8f6f2c7dd",
        notion_version=SUPPORTED_NOTION_VERSION,
        plan_digest=plan_digest(entries),
        approved_actions=frozenset({ReconciliationResult.UPDATE_EXISTING, ReconciliationResult.CREATE_MISSING}),
        property_allowlist=frozenset({"file_id", "Approved use"}),
        credential_route="injected-runtime-only",
        maximum_updates=1,
        maximum_creates=1,
        maximum_total_mutations=2,
        valid_until=NOW + timedelta(minutes=15),
        dry_run=True,
    )
    values.update(changes)
    return MutationAuthorization(**values)


def test_dry_run_is_deterministic_and_makes_zero_client_calls():
    entries = _entries()
    actions = build_mutation_actions(entries, _records(), property_mapping=MAPPING)
    auth = _authorization(entries)
    validate_plan_authorization(entries, auth)

    first = execute_mutation_actions(actions, auth, now=NOW)
    second = execute_mutation_actions(actions, auth, now=NOW)

    assert first == second
    assert [item.status for item in first] == ["dry-run", "dry-run"]


def test_plan_digest_mismatch_fails_closed():
    entries = _entries()
    auth = _authorization(entries, plan_digest="0" * 64)
    with pytest.raises(MutationAuthorizationError, match="plan digest"):
        validate_plan_authorization(entries, auth)


def test_expired_authorization_fails_before_client_call():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    auth = _authorization(valid_until=NOW - timedelta(seconds=1), dry_run=False)

    class Client:
        def update_page(self, **kwargs):
            raise AssertionError("must not call")

        def create_page(self, **kwargs):
            raise AssertionError("must not call")

    with pytest.raises(MutationAuthorizationError, match="expired"):
        execute_mutation_actions(actions, auth, client=Client(), now=NOW)


def test_property_outside_allowlist_fails_before_client_call():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    auth = _authorization(property_allowlist=frozenset({"file_id"}), dry_run=False)
    with pytest.raises(MutationAuthorizationError, match="allowlist"):
        execute_mutation_actions(actions, auth, client=object(), now=NOW)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"maximum_updates": 0}, "update ceiling"),
        ({"maximum_creates": 0}, "create ceiling"),
        ({"maximum_total_mutations": 1}, "total mutation ceiling"),
    ],
)
def test_mutation_ceilings_fail_closed(changes, message):
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    auth = _authorization(**changes)
    with pytest.raises(MutationAuthorizationError, match=message):
        execute_mutation_actions(actions, auth, now=NOW)


def test_unapproved_action_class_fails_closed():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    auth = _authorization(approved_actions=frozenset({ReconciliationResult.UPDATE_EXISTING}))
    with pytest.raises(MutationAuthorizationError, match="not authorized"):
        execute_mutation_actions(actions, auth, now=NOW)


def test_live_update_and_create_return_sanitized_outcomes():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    auth = _authorization(dry_run=False)

    class Client:
        def update_page(self, **kwargs):
            assert kwargs["page_id"] == "page-1"
            return {"id": "page-1", "url": "https://notion.example/page-1"}

        def create_page(self, **kwargs):
            assert kwargs["data_source_id"] == auth.data_source_id
            return {"id": "page-2", "url": "https://notion.example/page-2"}

    outcomes = execute_mutation_actions(actions, auth, client=Client(), now=NOW)
    assert [(item.status, item.page_id) for item in outcomes] == [
        ("applied", "page-1"),
        ("applied", "page-2"),
    ]


def test_mismatched_update_page_id_fails_closed():
    actions = build_mutation_actions(_entries()[:1], _records()[:1], property_mapping=MAPPING)
    entries = _entries()[:1]
    auth = _authorization(
        entries,
        maximum_creates=0,
        maximum_total_mutations=1,
        dry_run=False,
    )

    class Client:
        def update_page(self, **kwargs):
            return {"id": "wrong-page"}

    with pytest.raises(MutationExecutionError, match="unexpected page id"):
        execute_mutation_actions(actions, auth, client=Client(), now=NOW)


def test_external_exception_details_are_not_exposed():
    entries = _entries()[:1]
    actions = build_mutation_actions(entries, _records()[:1], property_mapping=MAPPING)
    auth = _authorization(entries, maximum_creates=0, maximum_total_mutations=1, dry_run=False)

    class Client:
        def update_page(self, **kwargs):
            raise RuntimeError("secret-token-should-not-escape")

    with pytest.raises(MutationExecutionError) as caught:
        execute_mutation_actions(actions, auth, client=Client(), now=NOW)
    assert "secret-token" not in str(caught.value)


def test_non_mutable_planner_entries_are_not_converted_to_actions():
    record = SourceAssetRecord(source_row="4", drive_file_id=None, excluded=True)
    entry = ReconciliationEntry(
        source_row="4",
        result=ReconciliationResult.EXCLUDED,
        identity_key=None,
    )
    assert build_mutation_actions((entry,), (record,), property_mapping=MAPPING) == ()
