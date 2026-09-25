"""Focused regression coverage for the #2283 live binding bootstrap."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.agent_os_notion_read_request import binding_verification as binding_verification_module
from scripts.agent_os_notion_read_request import parse_catalog
from scripts.agent_os_notion_read_request.binding_verification import (
    CANONICAL_REGISTRY_DATABASE_ID,
    CANONICAL_REGISTRY_TITLE,
    CANDY_BRANDING_STABLE_ID,
    CANDY_BRANDING_TITLE,
    CANDY_BRANDING_VERIFICATION_ISSUE_NUMBER,
    CANDY_BRANDING_VERIFICATION_REQUEST_ID,
    PHOTOGRAPHY_FOUNDATIONS_PAGE_ID,
    VERIFICATION_REQUEST_ID,
    VISUAL_ASSET_LIBRARY_DATABASE_ID,
    VISUAL_ASSET_LIBRARY_TITLE,
    admit_binding_verification_request,
    is_binding_verification_request_id,
    verify_additional_unit_binding,
    verify_candy_branding_binding,
    verify_live_bindings,
)
from scripts.agent_os_notion_read_request.models import NotionReadRequestError
from tests.agent_os_notion_read_request.notion_read_support import ACTOR, REPOSITORY, transport


@pytest.fixture
def staged_candy_catalog(monkeypatch):
    """Recreate the pre-promotion Candy state for verifier regression tests."""

    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "agent_os_notion_read_request"
        / "notion_read_catalog.json"
    )
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    staged = copy.deepcopy(payload)
    for unit in staged["canonical_units"]:
        if unit["canonical_unit_key"] == "candy-branding":
            unit["provider_page_id"] = None
            unit["verification_state"] = "unverified"
    catalog = parse_catalog(staged)
    monkeypatch.setattr(binding_verification_module, "load_catalog", lambda: catalog)
    return catalog


class VerificationAdapter:
    def __init__(self, *, visual_sources=None):
        self.calls = []
        self.visual_sources = visual_sources or [
            {"id": "visual-data-source-current", "name": VISUAL_ASSET_LIBRARY_TITLE}
        ]

    def execute(self, task):
        self.calls.append(dict(task.payload))
        action = task.payload["action"]
        if action == "get_database":
            database_id = task.payload["database_id"]
            if database_id == CANONICAL_REGISTRY_DATABASE_ID:
                output = {
                    "id": CANONICAL_REGISTRY_DATABASE_ID,
                    "title": CANONICAL_REGISTRY_TITLE,
                    "archived": False,
                    "in_trash": False,
                    "data_sources": [
                        {"id": "canonical-data-source-current", "name": CANONICAL_REGISTRY_TITLE}
                    ],
                }
            elif database_id == VISUAL_ASSET_LIBRARY_DATABASE_ID:
                output = {
                    "id": VISUAL_ASSET_LIBRARY_DATABASE_ID,
                    "title": VISUAL_ASSET_LIBRARY_TITLE,
                    "archived": False,
                    "in_trash": False,
                    "data_sources": self.visual_sources,
                }
            else:  # pragma: no cover - fixed vocabulary must make this unreachable
                raise AssertionError(database_id)
            return {"status": "success", "output": output}
        if action == "get_page":
            return {
                "status": "success",
                "output": {
                    "id": PHOTOGRAPHY_FOUNDATIONS_PAGE_ID,
                    "archived": False,
                    "in_trash": False,
                },
            }
        raise AssertionError(action)


def test_verification_request_is_exact_and_authority_stays_false() -> None:
    decision = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "admitted"
    assert decision["secret_dispatch_authorized"] is True
    assert decision["allowed_read_actions"] == ["get_database", "get_page"]
    assert decision["write_allowed"] is False
    assert decision["production_authorized"] is False
    assert decision["notion_write_reachable"] is False
    assert decision["gce_required"] is False


def test_verification_request_rejects_wrong_actor_or_issue() -> None:
    wrong_actor = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID, actor="someone-else"),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    wrong_issue = admit_binding_verification_request(
        transport(request_id=VERIFICATION_REQUEST_ID, issue_number=999),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert wrong_actor["secret_dispatch_authorized"] is False
    assert wrong_actor["reason_codes"] == ["actor-not-allowed"]
    assert wrong_issue["secret_dispatch_authorized"] is False
    assert wrong_issue["reason_codes"] == ["issue-target-mismatch"]


def test_live_verification_uses_exactly_two_databases_and_one_page() -> None:
    adapter = VerificationAdapter()
    evidence = verify_live_bindings(adapter, generated_at="run:1")

    assert [call["action"] for call in adapter.calls] == [
        "get_database",
        "get_database",
        "get_page",
    ]
    assert evidence["canonical_registry"]["data_source_id"] == "canonical-data-source-current"
    assert evidence["visual_asset_library"]["data_source_id"] == "visual-data-source-current"
    assert evidence["photography_foundations"]["provider_page_id"] == PHOTOGRAPHY_FOUNDATIONS_PAGE_ID
    assert evidence["notion_writes_performed"] is False
    assert evidence["drive_writes_performed"] is False
    assert evidence["gce_invoked"] is False


def test_ambiguous_data_source_identity_fails_closed() -> None:
    adapter = VerificationAdapter(
        visual_sources=[
            {"id": "one", "name": "Other"},
            {"id": "two", "name": "Also Other"},
        ]
    )
    with pytest.raises(NotionReadRequestError, match="data source identity is ambiguous"):
        verify_live_bindings(adapter, generated_at="run:1")


class CandyVerificationAdapter:
    def __init__(
        self,
        results,
        *,
        title_properties=("Canonical Unit Name",),
        data_source_id="canonical-data-source-current",
    ):
        self.calls = []
        self.results = results
        self.title_properties = title_properties
        self.data_source_id = data_source_id

    def execute(self, task):
        self.calls.append(dict(task.payload))
        action = task.payload["action"]
        if action == "get_data_source":
            return {
                "status": "success",
                "output": {
                    "id": self.data_source_id,
                    "properties": {
                        **{
                            name: {"id": f"title-{index}", "type": "title"}
                            for index, name in enumerate(self.title_properties)
                        },
                        "Aliases": {"id": "aliases", "type": "rich_text"},
                    },
                },
            }
        if action == "query_data_source":
            return {
                "status": "success",
                "output": {
                    "results": self.results,
                    "has_more": False,
                    "next_cursor": None,
                },
            }
        raise AssertionError(action)



def test_candy_binding_is_discovered_by_exact_registered_title_only(staged_candy_catalog) -> None:
    adapter = CandyVerificationAdapter(
        [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "archived": False,
                "in_trash": False,
            }
        ]
    )
    evidence = verify_candy_branding_binding(
        adapter,
        canonical_registry_data_source_id="canonical-data-source-current",
        generated_at="run:2816",
    )

    assert [call["action"] for call in adapter.calls] == [
        "get_data_source",
        "query_data_source",
    ]
    schema_call, query_call = adapter.calls
    assert schema_call["data_source_id"] == "canonical-data-source-current"
    assert query_call["data_source_id"] == "canonical-data-source-current"
    assert query_call["filter"] == {
        "property": "Canonical Unit Name",
        "title": {"equals": CANDY_BRANDING_TITLE},
    }
    assert query_call["max_pages"] == 1
    assert query_call["max_results"] == 2
    assert evidence["canonical_unit"] == {
        "canonical_unit_key": "candy-branding",
        "stable_id": CANDY_BRANDING_STABLE_ID,
        "provider_page_id": "33333333-3333-3333-3333-333333333333",
        "verification_state": "verified-current",
    }
    assert evidence["notion_writes_performed"] is False
    assert evidence["drive_writes_performed"] is False
    assert evidence["gce_invoked"] is False


@pytest.mark.parametrize(
    "title_properties",
    (
        (),
        ("First Title", "Second Title"),
    ),
)
def test_candy_binding_fails_closed_when_title_schema_is_missing_or_ambiguous(title_properties, staged_candy_catalog) -> None:
    with pytest.raises(
        NotionReadRequestError,
        match="exactly one title property",
    ):
        verify_candy_branding_binding(
            CandyVerificationAdapter(
                [],
                title_properties=title_properties,
            ),
            canonical_registry_data_source_id="canonical-data-source-current",
            generated_at="run:2816",
        )


def test_candy_binding_fails_closed_on_registry_data_source_identity_mismatch(staged_candy_catalog) -> None:
    with pytest.raises(
        NotionReadRequestError,
        match="data source identity mismatch",
    ):
        verify_candy_branding_binding(
            CandyVerificationAdapter(
                [],
                data_source_id="different-data-source",
            ),
            canonical_registry_data_source_id="canonical-data-source-current",
            generated_at="run:2816",
        )


@pytest.mark.parametrize(
    "results",
    (
        [],
        [
            {"id": "one", "archived": False, "in_trash": False},
            {"id": "two", "archived": False, "in_trash": False},
        ],
    ),
)
def test_candy_binding_missing_or_ambiguous_fails_closed(results, staged_candy_catalog) -> None:
    with pytest.raises(
        NotionReadRequestError,
        match="identity is missing or ambiguous",
    ):
        verify_candy_branding_binding(
            CandyVerificationAdapter(results),
            canonical_registry_data_source_id="canonical-data-source-current",
            generated_at="run:2816",
        )


def test_candy_verification_admission_is_finite_and_read_only(staged_candy_catalog) -> None:
    decision = admit_binding_verification_request(
        transport(
            request_id=CANDY_BRANDING_VERIFICATION_REQUEST_ID,
            issue_number=CANDY_BRANDING_VERIFICATION_ISSUE_NUMBER,
        ),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "admitted"
    assert decision["canonical_unit_key"] == "candy-branding"
    assert decision["allowed_read_actions"] == ["get_data_source", "query_data_source"]
    assert decision["secret_dispatch_authorized"] is True
    assert decision["write_allowed"] is False
    assert decision["production_authorized"] is False
    assert decision["notion_write_reachable"] is False
    assert decision["gce_required"] is False


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"issue_number": 2283}, "issue-target-mismatch"),
        ({"actor": "someone-else"}, "actor-not-allowed"),
        ({"run_attempt": 2}, "run-attempt-replay"),
        ({"execution_authorized": True}, "transport-claims-authority"),
        ({"request_id": "verify-something-else"}, "verification-request-mismatch"),
    ),
)
def test_candy_verification_admission_rejects_broadened_envelopes(overrides, reason, staged_candy_catalog) -> None:
    payload = {
        "request_id": CANDY_BRANDING_VERIFICATION_REQUEST_ID,
        "issue_number": CANDY_BRANDING_VERIFICATION_ISSUE_NUMBER,
        **overrides,
    }
    decision = admit_binding_verification_request(
        transport(**payload),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "rejected"
    assert decision["reason_codes"] == [reason]
    assert decision["secret_dispatch_authorized"] is False


def test_candy_binding_archived_or_trashed_fails_closed(staged_candy_catalog) -> None:
    for state in (
        {"archived": True, "in_trash": False},
        {"archived": False, "in_trash": True},
    ):
        with pytest.raises(
            NotionReadRequestError,
            match="canonical page is archived or trashed",
        ):
            verify_candy_branding_binding(
                CandyVerificationAdapter(
                    [{"id": "33333333-3333-3333-3333-333333333333", **state}]
                ),
                canonical_registry_data_source_id="canonical-data-source-current",
                generated_at="run:2816",
            )


def test_motion_typography_reuses_general_additional_unit_verifier() -> None:
    adapter = CandyVerificationAdapter(
        [
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "archived": False,
                "in_trash": False,
            }
        ]
    )

    decision = admit_binding_verification_request(
        transport(
            request_id="verify-motion-typography-binding",
            issue_number=2816,
        ),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "admitted"
    assert decision["canonical_unit_key"] == "motion-typography"
    assert decision["allowed_read_actions"] == ["get_data_source", "query_data_source"]

    evidence = verify_additional_unit_binding(
        adapter,
        canonical_unit_key="motion-typography",
        canonical_registry_data_source_id="canonical-data-source-current",
        generated_at="run:motion",
    )
    assert adapter.calls[1]["filter"] == {
        "property": "Canonical Unit Name",
        "title": {"equals": "Motion Typography"},
    }
    assert evidence["canonical_unit"] == {
        "canonical_unit_key": "motion-typography",
        "stable_id": "canonical-unit-motion-typography",
        "provider_page_id": "44444444-4444-4444-4444-444444444444",
        "verification_state": "verified-current",
    }


@pytest.mark.parametrize(
    "request_id",
    (
        "verify-photography-foundations-binding",
        "verify-unknown-unit-binding",
        "verify-candy-branding-anything",
    ),
)
def test_unregistered_or_ineligible_general_verifier_ids_fail_closed(request_id) -> None:
    decision = admit_binding_verification_request(
        transport(request_id=request_id, issue_number=2816),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )
    assert decision["status"] == "rejected"
    assert decision["reason_codes"] == ["verification-request-mismatch"]
    assert decision["secret_dispatch_authorized"] is False


def test_shipped_catalog_promotes_only_freshly_verified_candy_binding() -> None:
    catalog = binding_verification_module.load_catalog()

    candy = catalog.canonical_unit("candy-branding")
    assert candy is not None
    assert candy.provider_page_id == "3907ac78-3131-8132-8f84-f9fd633acba5"
    assert candy.verification_state == "verified-current"
    assert candy.dispatchable is True
    assert is_binding_verification_request_id("verify-candy-branding-binding") is False

    motion = catalog.canonical_unit("motion-typography")
    assert motion is not None
    assert motion.provider_page_id is None
    assert motion.verification_state == "unverified"
    assert motion.dispatchable is False
    assert is_binding_verification_request_id("verify-motion-typography-binding") is True


def test_binding_verification_routing_is_derived_from_finite_catalog() -> None:
    assert is_binding_verification_request_id(VERIFICATION_REQUEST_ID) is True
    assert is_binding_verification_request_id(CANDY_BRANDING_VERIFICATION_REQUEST_ID) is True
    assert is_binding_verification_request_id("verify-motion-typography-binding") is True
    for request_id in (
        "verify-unknown-unit-binding",
        "verify-candy-branding-anything",
        "motion-typography-canonical-unit",
        None,
    ):
        assert is_binding_verification_request_id(request_id) is False


def test_candy_cli_uses_existing_adapter_and_verified_registry_source(tmp_path, monkeypatch, staged_candy_catalog) -> None:
    canonical_source = binding_verification_module.load_catalog().source("canonical-unit")
    assert canonical_source is not None
    assert canonical_source.data_source_id is not None

    adapter = CandyVerificationAdapter(
        [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "archived": False,
                "in_trash": False,
            }
        ],
        data_source_id=canonical_source.data_source_id,
    )
    monkeypatch.setattr(binding_verification_module, "new_read_adapter", lambda: adapter)
    transport_path = tmp_path / "transport.json"
    transport_path.write_text(
        json.dumps(
            transport(
                request_id=CANDY_BRANDING_VERIFICATION_REQUEST_ID,
                issue_number=CANDY_BRANDING_VERIFICATION_ISSUE_NUMBER,
            )
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "result.json"

    exit_code = binding_verification_module.main(
        [
            "--transport",
            str(transport_path),
            "--repository",
            REPOSITORY,
            "--allowed-actor",
            ACTOR,
            "--generated-at",
            "run:2816",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    evidence = json.loads(output_path.read_text(encoding="utf-8"))
    assert evidence["admission"]["status"] == "admitted"
    assert evidence["dispatch_status"] == "completed"
    assert evidence["canonical_unit"]["canonical_unit_key"] == "candy-branding"
    assert evidence["canonical_unit"]["provider_page_id"] == (
        "33333333-3333-3333-3333-333333333333"
    )
    assert [call["action"] for call in adapter.calls] == [
        "get_data_source",
        "query_data_source",
    ]
    assert evidence["notion_writes_performed"] is False
    assert evidence["drive_writes_performed"] is False
    assert evidence["classroom_artifact_writes_performed"] is False
    assert evidence["gce_invoked"] is False
