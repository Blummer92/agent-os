from __future__ import annotations

import copy

import pytest

from instructional_workflow_contracts.live_operation_subject import CONTRACT_ID
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState
from scripts.agent_os_issue_acceptance.typed_subject_approval import (
    INSTRUCTIONAL_LIVE_SUBJECT_KIND,
    TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION,
    TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION,
    TypedSubjectReference,
    record_typed_subject_approval_decision,
    validate_typed_subject_reference,
)


def _invalid_subject() -> dict[str, object]:
    # Deliberately complete enough to prove validation, but with an unsupported
    # version so the public #1975 validator must reject it.
    return {
        "contract_version": "unsupported-live-subject-v9",
        "source": {},
        "material_requirement": {},
        "workspace": {},
        "operation": {},
        "gate_evidence_ids": [],
        "visual_reuse_evidence_ids": [],
        "authority": {},
    }


def test_typed_subject_versions_are_additive_successors():
    assert TYPED_SUBJECT_APPROVAL_SCHEMA_VERSION == "1.2"
    assert TYPED_SUBJECT_PROJECTION_SCHEMA_VERSION == "1.1"


def test_reference_accepts_only_canonical_instructional_kind_and_version():
    ref = TypedSubjectReference(
        INSTRUCTIONAL_LIVE_SUBJECT_KIND,
        CONTRACT_ID,
        "instructional-live-operation-subject:" + "a" * 64,
    )
    assert ref.subject_kind == INSTRUCTIONAL_LIVE_SUBJECT_KIND
    with pytest.raises(ValueError, match="kind"):
        TypedSubjectReference("other-kind", CONTRACT_ID, ref.subject_id)
    with pytest.raises(ValueError, match="schema version"):
        TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, "v9", ref.subject_id)
    with pytest.raises(ValueError, match="subject_id"):
        TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, CONTRACT_ID, "subject:free-form")


def test_typed_subject_requires_full_validated_object_not_arbitrary_id():
    with pytest.raises(TypeError, match="complete subject object"):
        validate_typed_subject_reference("instructional-live-operation-subject:" + "a" * 64)
    with pytest.raises(ValueError, match="typed approval subject is invalid"):
        validate_typed_subject_reference(_invalid_subject())


def test_authority_flags_are_structurally_false_on_reference_successor_types():
    # Construction of the wrapper records/projection is exercised by the existing
    # #398/#407 fixture family once a valid subject fixture is supplied. This
    # focused assertion prevents the new reference itself from carrying authority.
    ref = TypedSubjectReference(
        INSTRUCTIONAL_LIVE_SUBJECT_KIND,
        CONTRACT_ID,
        "instructional-live-operation-subject:" + "b" * 64,
    )
    assert not hasattr(ref, "execution_authorized")


def test_subject_reference_identity_changes_with_subject_id():
    first = TypedSubjectReference(
        INSTRUCTIONAL_LIVE_SUBJECT_KIND,
        CONTRACT_ID,
        "instructional-live-operation-subject:" + "a" * 64,
    )
    second = TypedSubjectReference(
        INSTRUCTIONAL_LIVE_SUBJECT_KIND,
        CONTRACT_ID,
        "instructional-live-operation-subject:" + "b" * 64,
    )
    assert first != second


def test_no_io_or_runtime_dependencies_are_imported():
    import scripts.agent_os_issue_acceptance.typed_subject_approval as module

    source = __import__("inspect").getsource(module)
    forbidden = (
        "workflow_scheduler",
        "googleapiclient",
        "requests",
        "subprocess",
        "credential",
    )
    for token in forbidden:
        assert token not in source
