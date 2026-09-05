from datetime import datetime, timedelta, timezone

import pytest

from visual_asset_sync.models import ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.mutation_adapter import (
    MutationAuthorization,
    MutationAuthorizationError,
    MutationExecutionError,
    NotionTransientMutationError,
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
        ReconciliationEntry(source_row="2", result=ReconciliationResult.UPDATE_EXISTING, identity_key=records[0].drive_file_id, matched_page_ids=("page-1",)),
        ReconciliationEntry(source_row="3", result=ReconciliationResult.CREATE_MISSING, identity_key=records[1].drive_file_id),
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
        maximum_retries=0,
        maximum_total_retry_delay=0,
    )
    values.update(changes)
    return MutationAuthorization(**values)


class GoodClient:
    def read_page_identity(self, **kwargs):
        return {"page_id": kwargs["page_id"], "identity_key": _records()[0].drive_file_id}

    def find_pages_by_identity(self, **kwargs):
        return ()

    def update_page(self, **kwargs):
        return {"id": kwargs["page_id"], "url": "https://notion.example/page-1"}

    def create_page(self, **kwargs):
        return {"id": "page-2", "url": "https://notion.example/page-2"}


def test_dry_run_is_deterministic_and_makes_zero_client_calls():
    entries = _entries()
    actions = build_mutation_actions(entries, _records(), property_mapping=MAPPING)
    auth = _authorization(entries)
    validate_plan_authorization(entries, auth)
    assert execute_mutation_actions(actions, auth, now=NOW) == execute_mutation_actions(actions, auth, now=NOW)


def test_plan_digest_mismatch_fails_closed():
    with pytest.raises(MutationAuthorizationError, match="plan digest"):
        validate_plan_authorization(_entries(), _authorization(plan_digest="0" * 64))


def test_expired_authorization_fails_before_client_call():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    with pytest.raises(MutationAuthorizationError, match="expired"):
        execute_mutation_actions(actions, _authorization(valid_until=NOW - timedelta(seconds=1), dry_run=False), client=GoodClient(), now=NOW)


def test_property_outside_allowlist_fails_before_client_call():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    with pytest.raises(MutationAuthorizationError, match="allowlist"):
        execute_mutation_actions(actions, _authorization(property_allowlist=frozenset({"file_id"}), dry_run=False), client=GoodClient(), now=NOW)


@pytest.mark.parametrize(("changes", "message"), [
    ({"maximum_updates": 0}, "update ceiling"),
    ({"maximum_creates": 0}, "create ceiling"),
    ({"maximum_total_mutations": 1}, "total mutation ceiling"),
])
def test_mutation_ceilings_fail_closed(changes, message):
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    with pytest.raises(MutationAuthorizationError, match=message):
        execute_mutation_actions(actions, _authorization(**changes), now=NOW)


def test_unapproved_action_class_fails_closed():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    with pytest.raises(MutationAuthorizationError, match="not authorized"):
        execute_mutation_actions(actions, _authorization(approved_actions=frozenset({ReconciliationResult.UPDATE_EXISTING})), now=NOW)


def test_live_update_and_create_require_preconditions_and_return_outcomes():
    actions = build_mutation_actions(_entries(), _records(), property_mapping=MAPPING)
    outcomes = execute_mutation_actions(actions, _authorization(dry_run=False), client=GoodClient(), now=NOW)
    assert [(item.status, item.page_id) for item in outcomes] == [("applied", "page-1"), ("applied", "page-2")]


def test_stale_update_identity_blocks_before_mutation():
    entries = _entries()[:1]
    actions = build_mutation_actions(entries, _records()[:1], property_mapping=MAPPING)

    class Client(GoodClient):
        def read_page_identity(self, **kwargs):
            return {"page_id": "page-1", "identity_key": "different"}
        def update_page(self, **kwargs):
            raise AssertionError("must not mutate")

    with pytest.raises(MutationExecutionError, match="stale or conflicting"):
        execute_mutation_actions(actions, _authorization(entries, maximum_creates=0, maximum_total_mutations=1, dry_run=False), client=Client(), now=NOW)


def test_create_precondition_existing_identity_blocks():
    entries = _entries()[1:]
    actions = build_mutation_actions(entries, _records()[1:], property_mapping=MAPPING)

    class Client(GoodClient):
        def find_pages_by_identity(self, **kwargs):
            return ({"id": "already-there", "identity_key": kwargs["identity_key"]},)
        def create_page(self, **kwargs):
            raise AssertionError("must not mutate")

    with pytest.raises(MutationExecutionError, match="existing identity"):
        execute_mutation_actions(actions, _authorization(entries, maximum_updates=0, maximum_total_mutations=1, dry_run=False), client=Client(), now=NOW)


def test_bounded_transient_update_retry_respects_retry_after():
    entries = _entries()[:1]
    actions = build_mutation_actions(entries, _records()[:1], property_mapping=MAPPING)
    sleeps = []

    class Client(GoodClient):
        attempts = 0
        def update_page(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise NotionTransientMutationError(2)
            return {"id": kwargs["page_id"]}

    outcomes = execute_mutation_actions(
        actions,
        _authorization(entries, maximum_creates=0, maximum_total_mutations=1, dry_run=False, maximum_retries=1, maximum_total_retry_delay=2),
        client=Client(), now=NOW, sleep=sleeps.append,
    )
    assert outcomes[0].status == "applied"
    assert sleeps == [2.0]


def test_ambiguous_create_reconciles_identity_before_any_retry():
    entries = _entries()[1:]
    actions = build_mutation_actions(entries, _records()[1:], property_mapping=MAPPING)

    class Client(GoodClient):
        searches = 0
        creates = 0
        def find_pages_by_identity(self, **kwargs):
            self.searches += 1
            if self.searches == 1:
                return ()
            return ({"id": "page-created", "url": "https://notion.example/page-created", "identity_key": kwargs["identity_key"]},)
        def create_page(self, **kwargs):
            self.creates += 1
            raise NotionTransientMutationError(1, ambiguous=True)

    client = Client()
    outcomes = execute_mutation_actions(
        actions,
        _authorization(entries, maximum_updates=0, maximum_total_mutations=1, dry_run=False, maximum_retries=1, maximum_total_retry_delay=1),
        client=client, now=NOW, sleep=lambda _: None,
    )
    assert outcomes[0].status == "applied-reconciled"
    assert client.creates == 1


def test_ambiguous_create_without_identity_never_retries_even_with_budget():
    entries = _entries()[1:]
    actions = build_mutation_actions(entries, _records()[1:], property_mapping=MAPPING)

    class Client(GoodClient):
        creates = 0
        def create_page(self, **kwargs):
            self.creates += 1
            raise NotionTransientMutationError(1, ambiguous=True)

    client = Client()
    with pytest.raises(MutationExecutionError, match="manual reconciliation"):
        execute_mutation_actions(
            actions,
            _authorization(entries, maximum_updates=0, maximum_total_mutations=1, dry_run=False, maximum_retries=2, maximum_total_retry_delay=2),
            client=client, now=NOW, sleep=lambda _: None,
        )
    assert client.creates == 1


def test_ambiguous_update_never_retries_even_with_budget():
    entries = _entries()[:1]
    actions = build_mutation_actions(entries, _records()[:1], property_mapping=MAPPING)

    class Client(GoodClient):
        updates = 0
        def update_page(self, **kwargs):
            self.updates += 1
            raise NotionTransientMutationError(1, ambiguous=True)

    client = Client()
    with pytest.raises(MutationExecutionError, match="manual reconciliation"):
        execute_mutation_actions(
            actions,
            _authorization(entries, maximum_creates=0, maximum_total_mutations=1, dry_run=False, maximum_retries=2, maximum_total_retry_delay=2),
            client=client, now=NOW, sleep=lambda _: None,
        )
    assert client.updates == 1


def test_external_exception_details_are_not_exposed():
    entries = _entries()[:1]
    actions = build_mutation_actions(entries, _records()[:1], property_mapping=MAPPING)

    class Client(GoodClient):
        def update_page(self, **kwargs):
            raise RuntimeError("secret-token-should-not-escape")

    with pytest.raises(MutationExecutionError) as caught:
        execute_mutation_actions(actions, _authorization(entries, maximum_creates=0, maximum_total_mutations=1, dry_run=False), client=Client(), now=NOW)
    assert "secret-token" not in str(caught.value)


def test_non_mutable_planner_entries_are_not_converted_to_actions():
    record = SourceAssetRecord(source_row="4", drive_file_id=None, excluded=True)
    entry = ReconciliationEntry(source_row="4", result=ReconciliationResult.EXCLUDED, identity_key=None)
    assert build_mutation_actions((entry,), (record,), property_mapping=MAPPING) == ()
