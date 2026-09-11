"""Fail-closed admission proofs for the #2283 bounded Notion read.

Admission is the only gate between low-trust GitHub transport evidence and a
secret-bearing step, so every rejection below must leave
``secret_dispatch_authorized`` false.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_notion_read_request import (
    REQUEST_CLASSES,
    admit_notion_read_request,
    parse_catalog,
    required_logical_sources,
)

from .notion_read_support import (
    ACTOR,
    CANONICAL_UNIT_REQUEST,
    ISSUE,
    REPOSITORY,
    VISUAL_ASSETS_REQUEST,
    transport,
    verified_payload,
)


def admit(payload, catalog, *, actor: str = ACTOR, repository: str = REPOSITORY):
    return admit_notion_read_request(
        payload,
        catalog=catalog,
        expected_repository=repository,
        expected_actor=actor,
    )


def test_trusted_canonical_request_is_admitted(verified_catalog) -> None:
    decision = admit(transport(), verified_catalog)

    assert decision.status == "admitted"
    assert decision.reason_codes == ("admitted",)
    assert decision.secret_dispatch_authorized is True
    assert decision.request_id == VISUAL_ASSETS_REQUEST
    assert decision.request_class == "visual-assets"
    assert decision.canonical_unit_key == "photography-foundations"
    assert decision.required_logical_sources == ("canonical-unit", "visual-asset-library")
    # Admission never widens authority.
    assert decision.write_allowed is False
    assert decision.production_authorized is False
    assert decision.notion_write_reachable is False
    assert decision.gce_required is False


def test_shipped_catalog_is_not_live_activated(shipped_catalog) -> None:
    """The repository-owned catalog must not dispatch before owner verification."""
    decision = admit(transport(), shipped_catalog)

    assert decision.status == "rejected"
    assert decision.reason_codes == ("canonical-unit-unverified",)
    assert decision.secret_dispatch_authorized is False


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (transport(actor="someone-else"), "actor-not-allowed"),
        (transport(actor=None), "actor-not-allowed"),
        (transport(repository="someone/else"), "repository-mismatch"),
        (transport(status="blocked"), "transport-not-accepted"),
        (transport(status="ignored"), "transport-not-accepted"),
        (transport(reason="accepted-envelope"), "transport-reason-mismatch"),
        (transport(reason="accepted-discovery-envelope"), "transport-reason-mismatch"),
        (transport(run_attempt=2), "run-attempt-replay"),
        (transport(run_attempt=0), "run-attempt-replay"),
        (transport(run_attempt="1"), "run-attempt-replay"),
        (transport(execution_authorized=True), "transport-claims-authority"),
        (transport(scheduler_invoked=True), "transport-claims-authority"),
        (transport(side_effects_performed=True), "transport-claims-authority"),
        (transport(issue_number=9999), "issue-target-mismatch"),
        (transport(issue_number=None), "issue-target-mismatch"),
        (transport(request_id=None), "request-id-malformed"),
        (transport(request_id=""), "request-id-malformed"),
        (transport(request_id="UPPER"), "request-id-malformed"),
        (transport(request_id="has space"), "request-id-malformed"),
        (transport(request_id="-leading"), "request-id-malformed"),
        (transport(request_id="trailing-"), "request-id-malformed"),
        (transport(request_id="double--hyphen"), "request-id-malformed"),
        (transport(request_id="a" * 64), "request-id-malformed"),
        (transport(request_id="search"), "request-id-unknown"),
        (transport(request_id="visual-assets"), "request-id-unknown"),
        (transport(request_id="notion-read-anything"), "request-id-unknown"),
        ("not-a-mapping", "transport-malformed"),
        (None, "transport-malformed"),
        ([], "transport-malformed"),
    ],
)
def test_rejections_fail_closed(verified_catalog, payload, reason: str) -> None:
    decision = admit(payload, verified_catalog)

    assert decision.status == "rejected"
    assert decision.reason_codes == (reason,)
    assert decision.secret_dispatch_authorized is False


@pytest.mark.parametrize(
    "request_id",
    [
        # Historical #962 leads and any other bare Notion identity.
        "da5cba48-50fd-4377-9790-8df8f6f2c7dd",
        "c5b202aa-83d1-4cc4-9992-f98af648e461",
        "da5cba4850fd43779790" + "8df8f6f2c7dd",
    ],
)
def test_arbitrary_notion_identities_cannot_become_request_identities(
    verified_catalog, request_id: str
) -> None:
    decision = admit(transport(request_id=request_id), verified_catalog)

    assert decision.status == "rejected"
    assert decision.reason_codes == ("request-id-malformed",)
    assert decision.secret_dispatch_authorized is False


def test_catalog_repository_drift_fails_closed(catalog_payload) -> None:
    payload = verified_payload(catalog_payload)
    payload["repository"] = "someone/else"

    decision = admit(transport(), parse_catalog(payload))

    assert decision.status == "rejected"
    assert decision.reason_codes == ("repository-mismatch",)


def test_unverified_source_binding_blocks_dispatch(catalog_payload) -> None:
    payload = verified_payload(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "visual-asset-library":
            source["verification_state"] = "unverified"

    decision = admit(transport(), parse_catalog(payload))

    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-unverified",)
    assert decision.secret_dispatch_authorized is False


def test_unbound_source_identity_blocks_dispatch(catalog_payload) -> None:
    payload = verified_payload(catalog_payload)
    for source in payload["sources"]:
        if source["logical_source"] == "visual-asset-library":
            source["data_source_id"] = None

    decision = admit(transport(), parse_catalog(payload))

    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-unverified",)


def test_missing_source_binding_blocks_dispatch(catalog_payload) -> None:
    payload = verified_payload(catalog_payload)
    payload["sources"] = [
        source
        for source in payload["sources"]
        if source["logical_source"] != "visual-asset-library"
    ]

    decision = admit(transport(), parse_catalog(payload))

    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-not-allowlisted",)


def test_request_classes_needing_unbound_sources_fail_closed(
    catalog_payload,
) -> None:
    """Only the minimal first path is bindable; wider classes stay fail-closed."""
    payload = verified_payload(catalog_payload)
    payload["requests"].append(
        {
            "request_id": "photography-foundations-current-curriculum",
            "request_class": "current-curriculum",
            "canonical_unit_key": "photography-foundations",
            "issue_number": ISSUE,
        }
    )

    decision = admit(
        transport(request_id="photography-foundations-current-curriculum"),
        parse_catalog(payload),
    )

    assert decision.status == "rejected"
    assert decision.reason_codes == ("source-not-allowlisted",)


def test_canonical_unit_request_needs_only_the_registry_source(
    verified_catalog,
) -> None:
    decision = admit(transport(request_id=CANONICAL_UNIT_REQUEST), verified_catalog)

    assert decision.status == "admitted"
    assert decision.required_logical_sources == ("canonical-unit",)


def test_request_sensitive_planning_is_preserved_per_class() -> None:
    """Each finite class keeps the existing #980 request-sensitive read plan."""
    assert required_logical_sources("canonical-unit") == ("canonical-unit",)
    assert required_logical_sources("visual-assets") == (
        "canonical-unit",
        "visual-asset-library",
    )
    assert required_logical_sources("teacher-modeling") == (
        "canonical-unit",
        "teacher-modeling",
    )
    # A visual-asset request must not drag in unrelated modeling, packet,
    # materials, readiness, or production evidence.
    for unrelated in (
        "teacher-modeling",
        "daily-generation-packet",
        "instructional-materials",
        "unit-alignment",
        "production-control",
        "curriculum-source-control",
    ):
        assert unrelated not in required_logical_sources("visual-assets")


def test_every_declared_request_class_has_a_read_plan() -> None:
    for request_class in REQUEST_CLASSES:
        sources = required_logical_sources(request_class)
        assert sources
        assert sources[0] == "canonical-unit"


def test_admission_reads_no_credential(monkeypatch, verified_catalog) -> None:
    """Admission must not consult the environment for a token."""
    monkeypatch.setenv("NOTION_TOKEN", "ntn_should_never_be_read")
    sentinel: list[str] = []

    import os

    real_getenv = os.environ.get

    def tracking_get(key, default=None):
        sentinel.append(key)
        return real_getenv(key, default)

    monkeypatch.setattr(os.environ, "get", tracking_get)

    decision = admit(transport(), verified_catalog)

    assert decision.status == "admitted"
    assert "NOTION_TOKEN" not in sentinel
