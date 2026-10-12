"""Focused tests for the governed source-schema request class (#2816).

The source-schema class lets a bounded trigger read a catalog-declared
source's property vocabulary (id/name/type triples) through the existing
#2283 route. Its plan is exactly one ``get_data_source`` step: no filter
step exists, so the #3476 coursewide guard is bypassed by construction.
An unverified source (icon-system today) fails closed at admission.
"""

from __future__ import annotations

import copy
import json

import pytest

from navigation_registry.connectors.curriculum_execution_surface_router import (
    READ_ONLY_ACTIONS,
)

from scripts.agent_os_notion_read_request import (
    NotionReadCatalog,
    NotionReadRequestError,
    NotionReadRequestRecord,
    admit_notion_read_request,
    parse_catalog,
)
from scripts.agent_os_notion_read_request.execution import (
    _bounded_read_task_executor,
    execute_source_schema,
)
from scripts.agent_os_notion_read_request.projection import (
    RESULT_KIND_SCHEMA,
    project_source_schema_result,
)
from scripts.agent_os_notion_read_request.runner import run_notion_read_request

from .notion_read_support import (
    ACTOR,
    GENERATED_AT,
    REPOSITORY,
    transport,
    verified_payload,
)

ISSUE = 2816
VAL_SCHEMA_REQUEST = "visual-asset-library-schema"
ICON_SCHEMA_REQUEST = "icon-system-schema"
VAL_DATA_SOURCE_ID = "ds-visual-asset-library"


@pytest.fixture
def schema_catalog(catalog_payload):
    """Verified catalog, except icon-system which stays unverified (fail-closed)."""
    payload = verified_payload(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "icon-system":
            source["data_source_id"] = None
            source["verification_state"] = "unverified"
    return parse_catalog(payload)


def schema_transport(request_id: str, **overrides):
    return transport(request_id=request_id, issue_number=ISSUE, **overrides)


def admitted_val_decision(schema_catalog):
    return admit_notion_read_request(
        schema_transport(VAL_SCHEMA_REQUEST),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


class SchemaExecutor:
    """Fake #936 executor returning a data-source-shaped adapter output."""

    def __init__(self, properties: dict | None = None):
        self.calls: list[dict] = []
        self._properties = (
            properties
            if properties is not None
            else {
                "Asset title": {
                    "id": "title",
                    "name": "Asset title",
                    "type": "title",
                    "title": {},
                },
                "Reusable Across Units?": {
                    "id": "%7D%3AsP",
                    "name": "Reusable Across Units?",
                    "type": "checkbox",
                    "checkbox": {},
                },
            }
        )

    def factory(self):
        return self.execute

    def execute(self, payload):
        self.calls.append(copy.deepcopy(dict(payload)))
        return {
            "status": "success",
            "message": "Notion 'get_data_source' succeeded",
            "output": {
                "id": VAL_DATA_SOURCE_ID,
                "url": "https://www.notion.so/should-be-dropped",
                "archived": False,
                "name": "Visual Asset Library",
                "properties": copy.deepcopy(self._properties),
                "parent": {"type": "workspace", "workspace": True},
                "created_time": "2026-01-01T00:00:00.000Z",
                "request_id": "req-should-be-dropped",
            },
        }


# --------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------


def test_val_schema_request_admitted(schema_catalog) -> None:
    decision = admitted_val_decision(schema_catalog)
    assert decision.status == "admitted"
    assert decision.request_class == "source-schema"
    assert decision.required_logical_sources == ("visual-asset-library",)
    assert decision.canonical_unit_key is None
    assert decision.secret_dispatch_authorized is True


def test_icon_system_schema_rejected_while_source_unverified(schema_catalog) -> None:
    decision = admit_notion_read_request(
        schema_transport(ICON_SCHEMA_REQUEST),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-unverified",)
    assert decision.secret_dispatch_authorized is False


def test_icon_system_schema_admitted_once_source_verified(verified_catalog) -> None:
    decision = admit_notion_read_request(
        schema_transport(ICON_SCHEMA_REQUEST),
        catalog=verified_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "admitted"
    assert decision.required_logical_sources == ("icon-system",)


def test_schema_request_on_wrong_issue_rejected(schema_catalog) -> None:
    decision = admit_notion_read_request(
        transport(request_id=VAL_SCHEMA_REQUEST, issue_number=2283),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    assert decision.reason_codes == ("issue-target-mismatch",)


def test_schema_record_must_not_carry_canonical_unit_key(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for record in payload["requests"]:
        if record["request_id"] == VAL_SCHEMA_REQUEST:
            record["canonical_unit_key"] = "photography-foundations"
    with pytest.raises(NotionReadRequestError):
        parse_catalog(payload)


def test_schema_record_unknown_logical_source_rejected(catalog_payload) -> None:
    payload = copy.deepcopy(catalog_payload)
    for record in payload["requests"]:
        if record["request_id"] == VAL_SCHEMA_REQUEST:
            record["logical_source"] = "no-such-source"
    with pytest.raises(NotionReadRequestError):
        parse_catalog(payload)


def test_admission_rejects_unallowlisted_source() -> None:
    record = NotionReadRequestRecord(
        request_id="ghost-schema",
        request_class="source-schema",
        canonical_unit_key=None,
        issue_number=ISSUE,
        logical_source="ghost-source",
    )
    catalog = NotionReadCatalog(
        schema_version="1.0",
        repository=REPOSITORY,
        credential_env_var="NOTION_TOKEN",
        requests=(record,),
        sources=(),
        canonical_units=(),
    )
    decision = admit_notion_read_request(
        schema_transport("ghost-schema"),
        catalog=catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-not-allowlisted",)


# --------------------------------------------------------------------------
# Execution: exactly one schema step, no filter step
# --------------------------------------------------------------------------


def test_execution_dispatches_single_schema_step_no_filter(schema_catalog) -> None:
    executor = SchemaExecutor()
    execution = execute_source_schema(
        admitted_val_decision(schema_catalog),
        catalog=schema_catalog,
        scheduler_task_executor_factory=executor.factory,
    )
    assert len(executor.calls) == 1
    (call,) = executor.calls
    assert call["action"] == "get_data_source"
    assert call["data_source_id"] == VAL_DATA_SOURCE_ID
    assert "filter" not in call
    assert execution["logical_source"] == "visual-asset-library"
    assert set(execution["properties"]) == {"Asset title", "Reusable Across Units?"}


def test_execution_rejects_non_success(schema_catalog) -> None:
    def factory():
        def execute(payload):
            return {"status": "failure", "message": "boom"}

        return execute

    with pytest.raises(NotionReadRequestError):
        execute_source_schema(
            admitted_val_decision(schema_catalog),
            catalog=schema_catalog,
            scheduler_task_executor_factory=factory,
        )


def test_execution_rejects_wrong_request_class(schema_catalog) -> None:
    from dataclasses import replace

    bad = admitted_val_decision(schema_catalog)
    forged = replace(bad, request_class="visual-assets")
    with pytest.raises(NotionReadRequestError):
        execute_source_schema(
            forged,
            catalog=schema_catalog,
            scheduler_task_executor_factory=SchemaExecutor().factory,
        )


def test_get_data_source_in_read_only_allowlist() -> None:
    assert "get_data_source" in READ_ONLY_ACTIONS
    seen: list[dict] = []

    def factory_payload(payload):
        seen.append(dict(payload))
        return {"status": "success"}

    bounded = _bounded_read_task_executor(factory_payload)
    bounded({"action": "get_data_source", "data_source_id": "ds-x"})
    assert seen == [{"action": "get_data_source", "data_source_id": "ds-x"}]
    with pytest.raises(NotionReadRequestError):
        bounded({"action": "delete_block", "block_id": "b"})


# --------------------------------------------------------------------------
# Projection: triples only, everything else dropped
# --------------------------------------------------------------------------

_EXPECTED_PAYLOAD_KEYS = {
    "schema_version",
    "result_kind",
    "repository",
    "issue_number",
    "request_id",
    "request_class",
    "source",
    "properties",
    "authority",
    "generated_at",
}
_EXPECTED_SOURCE_KEYS = {
    "logical_source",
    "display_name",
    "verification_state",
    "access",
}
_EXPECTED_TRIPLE_KEYS = {"property_id", "property_name", "property_type"}


def projected(schema_catalog, properties: dict | None = None):
    executor = SchemaExecutor(properties=properties)
    execution = execute_source_schema(
        admitted_val_decision(schema_catalog),
        catalog=schema_catalog,
        scheduler_task_executor_factory=executor.factory,
    )
    return project_source_schema_result(
        admitted_val_decision(schema_catalog),
        execution,
        catalog=schema_catalog,
        generated_at=GENERATED_AT,
    )


def test_projection_emits_triples_and_drops_adapter_extras(schema_catalog) -> None:
    result = projected(schema_catalog)
    assert result["result_kind"] == RESULT_KIND_SCHEMA
    assert result["properties"] == [
        {"property_id": "title", "property_name": "Asset title", "property_type": "title"},
        {
            "property_id": "%7D%3AsP",
            "property_name": "Reusable Across Units?",
            "property_type": "checkbox",
        },
    ]
    dumped = json.dumps(result)
    for dropped in (
        "should-be-dropped",
        "req-should-be-dropped",
        "2026-01-01T00:00:00.000Z",
        VAL_DATA_SOURCE_ID,
    ):
        assert dropped not in dumped


def test_projection_fixed_key_allowlist(schema_catalog) -> None:
    result = projected(schema_catalog)
    assert set(result) == _EXPECTED_PAYLOAD_KEYS
    assert set(result["source"]) == _EXPECTED_SOURCE_KEYS
    for triple in result["properties"]:
        assert set(triple) == _EXPECTED_TRIPLE_KEYS
    assert result["source"]["access"] == "read-only"
    assert all(value is False for value in result["authority"].values())


def test_projection_rejects_non_admitted(schema_catalog) -> None:
    decision = admit_notion_read_request(
        schema_transport(ICON_SCHEMA_REQUEST),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    with pytest.raises(NotionReadRequestError):
        project_source_schema_result(
            decision,
            {"properties": {}},
            catalog=schema_catalog,
            generated_at=GENERATED_AT,
        )


def test_projection_property_count_bounded(schema_catalog) -> None:
    oversized = {f"prop-{index}": {"id": str(index), "type": "rich_text"} for index in range(5000)}
    with pytest.raises(NotionReadRequestError):
        projected(schema_catalog, properties=oversized)


# --------------------------------------------------------------------------
# Runner end-to-end
# --------------------------------------------------------------------------


def test_runner_schema_end_to_end(schema_catalog) -> None:
    executor = SchemaExecutor()
    evidence = run_notion_read_request(
        schema_transport(VAL_SCHEMA_REQUEST),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=schema_catalog,
        scheduler_task_executor_factory=executor.factory,
    )
    assert evidence["dispatch_status"] == "completed"
    assert evidence["dispatch_reason"] == "bounded-source-schema-projected"
    assert evidence["result"]["result_kind"] == RESULT_KIND_SCHEMA
    assert evidence["result"]["request_id"] == VAL_SCHEMA_REQUEST
    for flag in (
        "notion_writes_performed",
        "drive_writes_performed",
        "classroom_artifact_writes_performed",
        "gce_invoked",
    ):
        assert evidence[flag] is False
    assert len(executor.calls) == 1


def test_runner_schema_rejected_before_dispatch(schema_catalog) -> None:
    executor = SchemaExecutor()
    evidence = run_notion_read_request(
        schema_transport(ICON_SCHEMA_REQUEST),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=schema_catalog,
        scheduler_task_executor_factory=executor.factory,
    )
    assert evidence["dispatch_status"] == "blocked"
    assert evidence["dispatch_reason"] == "source-unverified"
    assert evidence["result"] is None
    assert executor.calls == []
