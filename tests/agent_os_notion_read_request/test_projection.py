"""Public-projection proofs for the #2283 sanitized GitHub result.

The repository owner accepted public visibility of *sanitized* curriculum and
Visual Asset Library results. These tests prove what that sanitization actually
excludes, and that currentness/provenance/authority evidence survives it.
"""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_notion_read_request import (
    RESULT_KIND,
    NotionReadRequestError,
    admit_notion_read_request,
    parse_catalog,
    project_public_result,
    reject_credential_keys,
    run_notion_read_request,
)
from scripts.agent_os_notion_read_request.models import (
    PUBLIC_PROJECTABLE_CONTENT_CLASSES,
)
from .notion_read_support import (
    ACTOR,
    GENERATED_AT,
    REPOSITORY,
    RecordingExecutor,
    transport,
    verified_payload,
)

NOTION_TOKEN_VALUE = "ntn_ThisIsAFakeSecretValue0000000000000000000"


def admitted(catalog):
    return admit_notion_read_request(
        transport(),
        catalog=catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )


def state_payload(**overrides) -> dict:
    payload = {
        "contract_version": "curriculum-current-state-v1",
        "state_id": "current-state-abc123",
        "canonical_unit": {
            "stable_id": "canonical-unit-photography-foundations",
            "status": "active",
        },
        "request": {"action": "images", "artifact_type": "images"},
        "current_context": None,
        "resolved_day_id": None,
        "owner_states": [],
        "context_evidence": [],
        "stale_evidence": [],
        "contradictions": [],
        "unresolved_teacher_decision": None,
        "next_legitimate_owner": None,
        "disposition": "supported",
        "assets": {
            "matching_asset_exists": True,
            "approved_for_requested_use_exists": True,
            "approved_reusable_student_facing_exists": True,
            "production_authorized": False,
            "asset_ids": ["asset-a"],
            "eligible_asset_ids": ["asset-a"],
        },
        "reason_codes": [],
        "blockers": [],
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "notion_write_authorized": False,
            "drive_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
    }
    payload.update(overrides)
    return payload


def project(catalog, **overrides):
    return project_public_result(
        admitted(catalog),
        {
            "read_route": "agent-os-notion-reader",
            "state_status": "valid",
            "state_payload": state_payload(**overrides),
        },
        catalog=catalog,
        generated_at=GENERATED_AT,
    )


# --------------------------------------------------------------------------
# Required public fields survive projection
# --------------------------------------------------------------------------


def test_required_result_fields_are_present(verified_catalog) -> None:
    result = project(verified_catalog)

    assert result["result_kind"] == RESULT_KIND
    assert result["request_id"] == "photography-foundations-visual-assets"
    assert result["request_class"] == "visual-assets"
    assert result["canonical_unit"]["canonical_unit_key"] == "photography-foundations"
    assert result["canonical_unit"]["stable_id"]
    assert result["sources"]
    assert result["currentness"]["state_id"]
    assert result["currentness"]["disposition"] == "supported"
    assert result["provenance"]["curriculum_source_of_truth"] == "notion-working-curriculum"
    assert result["assets"]["production_authorized"] is False
    assert result["authority"]["write_allowed"] is False
    assert result["authority"]["production_authorized"] is False
    assert result["generated_at"] == GENERATED_AT


def test_source_identity_and_owner_class_survive(verified_catalog) -> None:
    result = project(
        verified_catalog,
        owner_states=[
            {
                "evidence_id": "evidence-modeling-01",
                "owner": "teacher-modeling",
                "decision_key": "modeling-handoff-ready",
                "value": "ready",
                "source_revision": 4,
                "observed_at": "2026-09-10T12:00:00Z",
                "reference": {
                    "system": "notion",
                    "stable_id": "notion-record-01",
                    "exact_location": "https://www.notion.so/private-page-abc",
                    "verification_evidence": "verified by teacher on 2026-09-10",
                },
            }
        ],
    )

    owner = result["owner_evidence"][0]
    assert owner["owner"] == "teacher-modeling"
    assert owner["decision_key"] == "modeling-handoff-ready"
    assert owner["source_revision"] == 4
    assert owner["reference"]["system"] == "notion"
    assert owner["reference"]["stable_id"] == "notion-record-01"
    # Private page location and free-text verification notes are dropped.
    assert "exact_location" not in owner["reference"]
    assert "verification_evidence" not in owner["reference"]
    assert "private-page-abc" not in json.dumps(result)


def test_missing_stale_conflicting_state_remains_explicit(verified_catalog) -> None:
    result = project(
        verified_catalog,
        disposition="needs-reconciliation",
        reason_codes=["evidence-stale"],
        blockers=["dependency-owner-evidence-missing"],
        stale_evidence=[
            {
                "evidence_id": "evidence-stale-01",
                "owner": "unit-alignment",
                "decision_key": "unit-generation-approval",
                "source_revision": 1,
                "observed_at": "2026-08-01T12:00:00Z",
            }
        ],
        contradictions=[
            {
                "kind": "value-conflict",
                "decision_key": "packet-generation-gate",
                "evidence_ids": ["evidence-a", "evidence-b"],
                "owners": ["daily-generation-packet"],
            }
        ],
        unresolved_teacher_decision="Reconcile current owner state.",
        next_legitimate_owner="unit-alignment",
    )

    currentness = result["currentness"]
    assert currentness["disposition"] == "needs-reconciliation"
    assert currentness["reason_codes"] == ["evidence-stale"]
    assert currentness["blockers"] == ["dependency-owner-evidence-missing"]
    assert currentness["stale_evidence"][0]["evidence_id"] == "evidence-stale-01"
    assert currentness["contradictions"][0]["kind"] == "value-conflict"
    assert currentness["unresolved_teacher_decision"] == "Reconcile current owner state."
    assert currentness["next_legitimate_owner"] == "unit-alignment"


# --------------------------------------------------------------------------
# Sensitive data and credentials cannot be projected
# --------------------------------------------------------------------------


def test_unknown_upstream_fields_are_dropped_by_default(verified_catalog) -> None:
    """A new upstream field is never published merely because it appeared."""
    result = project(
        verified_catalog,
        owner_states=[
            {
                "evidence_id": "evidence-01",
                "owner": "unit-alignment",
                "decision_key": "unit-generation-approval",
                "value": "approved",
                "source_revision": 2,
                "observed_at": "2026-09-10T12:00:00Z",
                "reference": {"system": "notion", "stable_id": "notion-01"},
                # Sensitive/private fields an upstream change might introduce.
                "student_name": "A Real Student",
                "student_iep_note": "confidential accommodation detail",
                "parent_email": "parent@example.invalid",
                "raw_page_body": "private teacher planning prose",
            }
        ],
    )

    owner = result["owner_evidence"][0]
    assert set(owner) <= {
        "evidence_id",
        "owner",
        "decision_key",
        "value",
        "source_revision",
        "observed_at",
        "reference",
    }
    serialized = json.dumps(result)
    for sensitive in (
        "A Real Student",
        "confidential accommodation detail",
        "parent@example.invalid",
        "private teacher planning prose",
    ):
        assert sensitive not in serialized


def test_provider_data_source_identities_are_not_published(verified_catalog) -> None:
    result = project(verified_catalog)
    serialized = json.dumps(result)

    for binding in verified_catalog.sources:
        assert binding.data_source_id not in serialized
    assert all("data_source_id" not in source for source in result["sources"])


@pytest.mark.parametrize(
    "payload",
    [
        {"notion_token": NOTION_TOKEN_VALUE},
        {"authorization": f"Bearer {NOTION_TOKEN_VALUE}"},
        {"headers": {"Authorization": f"Bearer {NOTION_TOKEN_VALUE}"}},
        {"nested": [{"api_key": NOTION_TOKEN_VALUE}]},
        {"evidence": {"secret_value": "anything"}},
        {"session_cookie": "abc"},
        {"password": "hunter2"},
        {"credential_hint": "starts with ntn_"},
    ],
)
def test_credential_class_values_cannot_be_published(payload) -> None:
    with pytest.raises(NotionReadRequestError, match="credential-class key"):
        reject_credential_keys(payload)


def test_credential_class_boolean_flags_are_allowed() -> None:
    """A boolean cannot carry a secret, so state flags stay publishable."""
    reject_credential_keys({"secret_dispatch_authorized": True})
    reject_credential_keys({"token_present": False})


def test_full_evidence_envelope_never_carries_a_token(
    monkeypatch, verified_catalog
) -> None:
    monkeypatch.setenv("NOTION_TOKEN", NOTION_TOKEN_VALUE)

    evidence = run_notion_read_request(
        transport(),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=verified_catalog,
        scheduler_task_executor_factory=RecordingExecutor().factory,
    )

    serialized = json.dumps(evidence)
    assert NOTION_TOKEN_VALUE not in serialized
    assert "ntn_" not in serialized
    assert "Bearer" not in serialized
    assert "Authorization" not in serialized


def test_authority_widening_from_upstream_is_refused(verified_catalog) -> None:
    with pytest.raises(NotionReadRequestError, match="not fail-closed"):
        project(
            verified_catalog,
            authority={
                "execution_authorized": False,
                "production_authorized": True,
            },
        )


def test_only_public_projectable_content_classes_can_be_bound(catalog_payload) -> None:
    payload = verified_payload(catalog_payload)
    payload["sources"][0]["content_class"] = "sensitive-student-data"

    with pytest.raises(NotionReadRequestError, match="not public-projectable"):
        parse_catalog(payload)

    assert "sensitive-student-data" not in PUBLIC_PROJECTABLE_CONTENT_CLASSES


def test_oversized_evidence_collections_fail_closed(verified_catalog) -> None:
    with pytest.raises(NotionReadRequestError, match="exceeds the read limit"):
        project(
            verified_catalog,
            owner_states=[
                {
                    "evidence_id": f"evidence-{index:02d}",
                    "owner": "unit-alignment",
                    "decision_key": "unit-generation-approval",
                    "value": "approved",
                    "source_revision": 1,
                    "observed_at": "2026-09-10T12:00:00Z",
                }
                for index in range(25)
            ],
        )


def test_rejected_admission_cannot_be_projected(verified_catalog) -> None:
    decision = admit_notion_read_request(
        transport(actor="someone-else"),
        catalog=verified_catalog,
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
    )

    with pytest.raises(NotionReadRequestError, match="only an admitted request"):
        project_public_result(
            decision,
            {"state_payload": state_payload()},
            catalog=verified_catalog,
            generated_at=GENERATED_AT,
        )
