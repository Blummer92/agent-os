"""Focused tests for the Tier-2 bounded Reuse status select-options projection (#2816).

The source-schema projection emits select-option metadata only for the
verified Visual Asset Library "Reuse status" property (id ``MR%3Do``):
option stable ids and display names, nothing else. Every other property
keeps the triple-only projection. Malformed, unauthorized, or ambiguous
source data fails closed; the existing governed reader, route, and
authorization are reused unchanged.
"""

from __future__ import annotations

import copy

import pytest

from scripts.agent_os_notion_read_request import (
    NotionReadRequestError,
    admit_notion_read_request,
    parse_catalog,
)
from scripts.agent_os_notion_read_request.execution import execute_source_schema
from scripts.agent_os_notion_read_request.projection import (
    MAX_SELECT_OPTIONS,
    REUSE_STATUS_PROPERTY_ID,
    RESULT_KIND_SCHEMA,
    project_source_schema_result,
    reject_credential_keys,
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

EXPECTED_PAYLOAD_KEYS = {
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
EXPECTED_SOURCE_KEYS = {
    "logical_source",
    "display_name",
    "verification_state",
    "access",
}


def _reuse_status_property(options):
    return {
        "id": REUSE_STATUS_PROPERTY_ID,
        "name": "Reuse status",
        "type": "select",
        "select": {"options": options},
    }


def _option(option_id, name, **extra):
    option = {"id": option_id, "name": name}
    option.update(extra)
    return option


@pytest.fixture
def schema_catalog(catalog_payload):
    """Verified catalog, except icon-system which stays unverified (fail-closed)."""
    payload = verified_payload(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "icon-system":
            source["data_source_id"] = None
            source["verification_state"] = "unverified"
    return parse_catalog(payload)


def _admitted_val_decision(schema_catalog):
    return admit_notion_read_request(
        transport(request_id=VAL_SCHEMA_REQUEST, issue_number=ISSUE),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


class OptionsExecutor:
    """Fake #936 executor returning a VAL-shaped schema with select options."""

    def __init__(self, properties):
        self._properties = properties

    def factory(self):
        return self.execute

    def execute(self, payload):
        assert payload["action"] == "get_data_source"
        return {
            "status": "success",
            "output": {"properties": copy.deepcopy(self._properties)},
        }


def _project(schema_catalog, properties):
    decision = _admitted_val_decision(schema_catalog)
    execution = execute_source_schema(
        decision,
        catalog=schema_catalog,
        scheduler_task_executor_factory=OptionsExecutor(properties).factory,
    )
    return project_source_schema_result(
        decision,
        execution,
        catalog=schema_catalog,
        generated_at=GENERATED_AT,
    )


# --------------------------------------------------------------------------
# Successful retrieval: bound property, names + stable ids only
# --------------------------------------------------------------------------


def test_bound_property_emits_option_id_and_name_only(schema_catalog) -> None:
    properties = {
        "Reuse status": _reuse_status_property(
            [
                _option("opt-1", "Approved", color="green", extra_field="dropped"),
                _option("opt-2", "Draft", color="yellow"),
            ]
        ),
        "Asset title": {
            "id": "title",
            "name": "Asset title",
            "type": "title",
            "title": {},
        },
    }
    result = _project(schema_catalog, properties)

    assert set(result.keys()) == EXPECTED_PAYLOAD_KEYS
    assert result["result_kind"] == RESULT_KIND_SCHEMA
    assert set(result["source"].keys()) == EXPECTED_SOURCE_KEYS
    assert result["source"]["logical_source"] == "visual-asset-library"
    assert result["source"]["access"] == "read-only"

    by_name = {p["property_name"]: p for p in result["properties"]}
    reuse = by_name["Reuse status"]
    assert reuse["property_id"] == REUSE_STATUS_PROPERTY_ID
    assert reuse["property_type"] == "select"
    assert reuse["select_options"] == [
        {"option_id": "opt-1", "option_name": "Approved"},
        {"option_id": "opt-2", "option_name": "Draft"},
    ]
    # No other property carries options; no color or extra field leaks anywhere.
    assert "select_options" not in by_name["Asset title"]
    assert "color" not in str(result["properties"])
    assert "extra_field" not in str(result["properties"])
    reject_credential_keys(result, "result")


def test_empty_options_emits_empty_list(schema_catalog) -> None:
    properties = {"Reuse status": _reuse_status_property([])}
    result = _project(schema_catalog, properties)
    (triple,) = result["properties"]
    assert triple["select_options"] == []


def test_unbound_select_property_emits_no_options(schema_catalog) -> None:
    properties = {
        "Other select": {
            "id": "other-id",
            "name": "Other select",
            "type": "select",
            "select": {"options": [_option("x", "X")]},
        },
    }
    result = _project(schema_catalog, properties)
    (triple,) = result["properties"]
    assert set(triple.keys()) == {"property_id", "property_name", "property_type"}


# --------------------------------------------------------------------------
# Fail-closed: malformed or ambiguous bound property
# --------------------------------------------------------------------------


def test_bound_id_with_non_select_type_fails_closed(schema_catalog) -> None:
    properties = {
        "Reuse status": {
            "id": REUSE_STATUS_PROPERTY_ID,
            "name": "Reuse status",
            "type": "rich_text",
            "rich_text": {},
        },
    }
    with pytest.raises(NotionReadRequestError, match="not a select"):
        _project(schema_catalog, properties)


def test_bound_property_missing_select_schema_fails_closed(schema_catalog) -> None:
    properties = {
        "Reuse status": {
            "id": REUSE_STATUS_PROPERTY_ID,
            "name": "Reuse status",
            "type": "select",
        },
    }
    with pytest.raises(NotionReadRequestError, match="missing select schema"):
        _project(schema_catalog, properties)


@pytest.mark.parametrize(
    "options",
    [
        "not-a-list",
        {"options": []},
        None,
    ],
)
def test_bound_property_malformed_options_container_fails_closed(
    schema_catalog, options
) -> None:
    prop = _reuse_status_property([])
    prop["select"]["options"] = options
    with pytest.raises(NotionReadRequestError, match="malformed options"):
        _project(schema_catalog, {"Reuse status": prop})


@pytest.mark.parametrize(
    "option",
    [
        "not-a-mapping",
        {"id": "opt-1"},  # missing name
        {"name": "Approved"},  # missing id
        {"id": "", "name": "Approved"},  # empty id
        {"id": "opt-1", "name": ""},  # empty name
    ],
)
def test_bound_property_malformed_option_fails_closed(schema_catalog, option) -> None:
    properties = {"Reuse status": _reuse_status_property([option])}
    with pytest.raises(NotionReadRequestError):
        _project(schema_catalog, properties)


def test_bound_property_oversized_options_fails_closed(schema_catalog) -> None:
    options = [_option(f"opt-{i}", f"Option {i}") for i in range(MAX_SELECT_OPTIONS + 1)]
    properties = {"Reuse status": _reuse_status_property(options)}
    with pytest.raises(NotionReadRequestError, match="exceeds the option bound"):
        _project(schema_catalog, properties)


def test_error_responses_carry_no_option_data(schema_catalog) -> None:
    properties = {
        "Reuse status": _reuse_status_property([{"id": "s3cr3t", "name": "tok-abc"}])
    }
    # Well-formed here; the point is error paths never interpolate values.
    bad = _reuse_status_property([{"id": "opt-1"}])  # missing name -> error
    with pytest.raises(NotionReadRequestError) as excinfo:
        _project(schema_catalog, {"Reuse status": bad})
    assert "opt-1" not in str(excinfo.value)


# --------------------------------------------------------------------------
# Authorization and existing contracts are unchanged
# --------------------------------------------------------------------------


def test_non_admitted_request_rejected_before_projection(schema_catalog) -> None:
    decision = admit_notion_read_request(
        transport(request_id=VAL_SCHEMA_REQUEST, issue_number=9999),
        catalog=schema_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision.status == "rejected"
    properties = {"Reuse status": _reuse_status_property([_option("o", "O")])}
    with pytest.raises(NotionReadRequestError):
        project_source_schema_result(
            decision,
            {"properties": properties},
            catalog=schema_catalog,
            generated_at=GENERATED_AT,
        )


def test_unauthorized_runner_path_returns_no_option_metadata(schema_catalog) -> None:
    evidence = run_notion_read_request(
        transport(request_id=VAL_SCHEMA_REQUEST, issue_number=9999),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        scheduler_task_executor_factory=OptionsExecutor({}).factory,
    )
    assert evidence["dispatch_status"] == "blocked"
    assert evidence["result"] is None
    assert "select_options" not in str(evidence)


def test_end_to_end_runner_path_uses_existing_route(schema_catalog) -> None:
    properties = {
        "Reuse status": _reuse_status_property([_option("opt-9", "Archived")]),
    }
    evidence = run_notion_read_request(
        transport(request_id=VAL_SCHEMA_REQUEST, issue_number=ISSUE),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        scheduler_task_executor_factory=OptionsExecutor(properties).factory,
    )
    assert evidence["dispatch_status"] == "completed"
    assert evidence["dispatch_reason"] == "bounded-source-schema-projected"
    (triple,) = evidence["result"]["properties"]
    assert triple["select_options"] == [
        {"option_id": "opt-9", "option_name": "Archived"}
    ]
