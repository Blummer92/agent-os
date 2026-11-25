from __future__ import annotations

from collections import UserDict
from enum import Enum
from types import SimpleNamespace

import pytest

from instructional_workflow_contracts.common import FrozenObject
from instructional_workflow_contracts.live_operation_subject import CONTRACT_ID
from scripts.agent_os_issue_acceptance import typed_subject_approval as binding
from scripts.agent_os_issue_acceptance.typed_subject_approval import (
    INSTRUCTIONAL_LIVE_SUBJECT_KIND,
    TypedSubjectReference,
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


def test_uppercase_digest_is_canonicalized_without_relaxing_the_prefix():
    prefix = "instructional-live-operation-subject:"
    ref = TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, CONTRACT_ID, prefix + "A" * 64)
    assert ref.subject_id == prefix + "a" * 64
    with pytest.raises(ValueError, match="malformed"):
        TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, CONTRACT_ID, prefix.upper() + "a" * 64)
    with pytest.raises(ValueError, match="malformed"):
        TypedSubjectReference(INSTRUCTIONAL_LIVE_SUBJECT_KIND, CONTRACT_ID, prefix + "G" * 64)


def test_plain_dict_requirement_does_not_dispatch_custom_mapping():
    class Custom(UserDict):
        def __iter__(self):
            pytest.fail("custom mapping executed")

    with pytest.raises(ValueError, match="plain dict"):
        validate_typed_subject_reference(Custom())


@pytest.mark.parametrize("fail", [False, True])
def test_validator_failure_is_value_error_without_unbounded_details(monkeypatch, fail):
    def validate(_raw):
        if fail:
            raise RuntimeError("raw" * 5000)
        return SimpleNamespace(status="invalid", record=None, reason_codes=("X" * 5000,) * 20, details=("raw" * 5000,))

    monkeypatch.setattr(binding, "validate_live_operation_subject", validate)
    with pytest.raises(ValueError) as caught:
        validate_typed_subject_reference({})
    assert "raw" not in str(caught.value)
    assert len(str(caught.value)) < 320


@pytest.mark.parametrize("mismatch", [False, True])
def test_equivalent_status_enum_and_validated_id_binding(monkeypatch, mismatch):
    class ReloadedStatus(str, Enum):
        VALID = "valid"

    subject_id = "instructional-live-operation-subject:" + "a" * 64
    payload_id = "instructional-live-operation-subject:" + "b" * 64 if mismatch else subject_id
    record = SimpleNamespace(contract_version=CONTRACT_ID, record_id=subject_id, payload=FrozenObject((("subject_id", payload_id),)))
    monkeypatch.setattr(binding, "validate_live_operation_subject", lambda _: SimpleNamespace(status=ReloadedStatus.VALID, record=record, reason_codes=(), details=()))
    if mismatch:
        with pytest.raises(ValueError, match="does not match"):
            validate_typed_subject_reference({})
    else:
        assert validate_typed_subject_reference({}).subject_id == subject_id
