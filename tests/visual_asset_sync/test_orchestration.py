from datetime import datetime, timedelta, timezone

import pytest

from visual_asset_sync.models import ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.mutation_adapter import MutationAuthorization, build_mutation_actions, plan_digest
from visual_asset_sync.notion_adapter import SUPPORTED_NOTION_VERSION
from visual_asset_sync.orchestration import OrchestrationConfig, OrchestrationError, run_once

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def _case(*, dry_run=True):
    record = SourceAssetRecord(
        source_row="2",
        drive_file_id="1AbCdEfGhIjKlMnOpQrStUvWxYz123456",
        approved_use="Slides",
    )
    entry = ReconciliationEntry(
        source_row="2",
        result=ReconciliationResult.UPDATE_EXISTING,
        identity_key=record.drive_file_id,
        matched_page_ids=("page-1",),
    )
    actions = build_mutation_actions(
        (entry,),
        (record,),
        property_mapping={"drive_file_id": "file_id", "approved_use": "Approved use"},
    )
    auth = MutationAuthorization(
        data_source_id="da5cba48-50fd-4377-9790-8df8f6f2c7dd",
        notion_version=SUPPORTED_NOTION_VERSION,
        plan_digest=plan_digest((entry,)),
        approved_actions=frozenset({ReconciliationResult.UPDATE_EXISTING}),
        property_allowlist=frozenset({"file_id", "Approved use"}),
        credential_route="injected-runtime-only",
        maximum_updates=1,
        maximum_creates=0,
        maximum_total_mutations=1,
        valid_until=NOW + timedelta(minutes=10),
        dry_run=dry_run,
    )
    return (entry,), actions, auth


def test_defaults_are_disabled_and_inert():
    entries, actions, auth = _case()
    calls = []
    receipt = run_once(
        config=OrchestrationConfig(),
        entries=entries,
        actions=actions,
        authorization=auth,
        kill_switch_active=lambda: calls.append("kill") or False,
        acquire_lease=lambda: calls.append("acquire") or True,
        release_lease=lambda: calls.append("release"),
        now=NOW,
    )
    assert receipt.status == "disabled"
    assert calls == []


def test_kill_switch_blocks_before_lease():
    entries, actions, auth = _case()
    calls = []
    with pytest.raises(OrchestrationError, match="kill switch"):
        run_once(
            config=OrchestrationConfig(schedule_enabled=True, mutation_enabled=True),
            entries=entries,
            actions=actions,
            authorization=auth,
            kill_switch_active=lambda: True,
            acquire_lease=lambda: calls.append("acquire") or True,
            release_lease=lambda: calls.append("release"),
            now=NOW,
        )
    assert calls == []


def test_lease_released_when_second_kill_switch_check_blocks():
    entries, actions, auth = _case()
    checks = iter((False, True))
    calls = []
    with pytest.raises(OrchestrationError, match="before mutation"):
        run_once(
            config=OrchestrationConfig(schedule_enabled=True, mutation_enabled=True),
            entries=entries,
            actions=actions,
            authorization=auth,
            kill_switch_active=lambda: next(checks),
            acquire_lease=lambda: calls.append("acquire") or True,
            release_lease=lambda: calls.append("release"),
            now=NOW,
        )
    assert calls == ["acquire", "release"]


def test_lease_released_when_client_fails():
    entries, actions, auth = _case(dry_run=False)
    calls = []

    class Client:
        def update_page(self, **kwargs):
            raise RuntimeError("private failure detail")

    with pytest.raises(Exception):
        run_once(
            config=OrchestrationConfig(schedule_enabled=True, mutation_enabled=True),
            entries=entries,
            actions=actions,
            authorization=auth,
            kill_switch_active=lambda: False,
            acquire_lease=lambda: calls.append("acquire") or True,
            release_lease=lambda: calls.append("release"),
            client=Client(),
            now=NOW,
        )
    assert calls == ["acquire", "release"]


def test_enabled_dry_run_completes_without_client():
    entries, actions, auth = _case()
    calls = []
    receipt = run_once(
        config=OrchestrationConfig(schedule_enabled=True, mutation_enabled=True),
        entries=entries,
        actions=actions,
        authorization=auth,
        kill_switch_active=lambda: False,
        acquire_lease=lambda: calls.append("acquire") or True,
        release_lease=lambda: calls.append("release"),
        now=NOW,
    )
    assert receipt.status == "completed"
    assert receipt.outcomes[0].status == "dry-run"
    assert calls == ["acquire", "release"]
