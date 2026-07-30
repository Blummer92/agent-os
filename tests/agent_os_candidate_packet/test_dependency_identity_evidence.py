"""AOS-AUTO1A2 (#776): canonical dependency-identity evidence boundary.

Covers the immutable model, its fail-closed validation, and its canonical
serialization. Stage-level carry-through and #750 backward compatibility live in
``test_readiness_stage.py``, which already owns the stage fixtures.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet import readiness_stage, stage_models
from scripts.agent_os_candidate_packet.stage_models import (
    DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON,
    DEPENDENCY_IDENTITY_NOT_SUPPLIED,
    DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    canonical_bytes,
    dependency_identity_evidence_from_dict,
    dependency_identity_evidence_to_dict,
)

_PROVENANCE = ("caller:structured-dependency-input",)


def _resolved(*dependency_ids: object) -> DependencyIdentityEvidence:
    return DependencyIdentityEvidence(
        status=DependencyIdentityStatus.RESOLVED,
        dependency_ids=dependency_ids,
        provenance=_PROVENANCE,
    )


# --------------------------------------------------------------------------
# Status semantics: the four states stay distinct and machine-readable.
# --------------------------------------------------------------------------


def test_zero_dependencies_is_absent_not_an_empty_resolved_set() -> None:
    evidence = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT,
        provenance=("caller:structured-input-declared-zero-dependencies",),
    )
    assert evidence.status == DependencyIdentityStatus.ABSENT
    assert evidence.dependency_ids == ()
    assert evidence.provenance == (
        "caller:structured-input-declared-zero-dependencies",
    )
    # An empty resolved set is not a legal way to say "no dependencies".
    with pytest.raises(ValueError):
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED,
            dependency_ids=(),
            provenance=_PROVENANCE,
        )


def test_one_resolved_dependency_preserves_the_exact_identity() -> None:
    evidence = _resolved("issue-751")
    assert evidence.status == DependencyIdentityStatus.RESOLVED
    assert evidence.dependency_ids == ("issue-751",)
    assert evidence.reason_codes == ()


def test_one_unresolved_dependency_asserts_no_identities() -> None:
    evidence = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.UNRESOLVED,
        provenance=("caller:structured-input-declared-one-dependency",),
        reason_codes=("dependency-identity.declaration-unresolved",),
    )
    assert evidence.status == DependencyIdentityStatus.UNRESOLVED
    assert evidence.dependency_ids == ()
    assert evidence.reason_codes == ("dependency-identity.declaration-unresolved",)


def test_absent_evidence_requires_provenance() -> None:
    with pytest.raises(ValueError):
        DependencyIdentityEvidence(status=DependencyIdentityStatus.ABSENT)


def test_unavailable_evidence_requires_a_reason_code() -> None:
    with pytest.raises(ValueError):
        DependencyIdentityEvidence(status=DependencyIdentityStatus.UNAVAILABLE)
    evidence = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.UNAVAILABLE,
        reason_codes=("dependency-identity.source-unreadable",),
    )
    assert evidence.dependency_ids == ()


def test_absent_and_unavailable_stay_distinguishable() -> None:
    absent = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.ABSENT, provenance=_PROVENANCE
    )
    assert absent.status != DEPENDENCY_IDENTITY_NOT_SUPPLIED.status
    assert dependency_identity_evidence_to_dict(absent)["status"] == "absent"
    assert (
        dependency_identity_evidence_to_dict(DEPENDENCY_IDENTITY_NOT_SUPPLIED)["status"]
        == "unavailable"
    )


def test_not_supplied_sentinel_fails_closed_to_unavailable() -> None:
    assert DEPENDENCY_IDENTITY_NOT_SUPPLIED.status == (
        DependencyIdentityStatus.UNAVAILABLE
    )
    assert DEPENDENCY_IDENTITY_NOT_SUPPLIED.dependency_ids == ()
    assert DEPENDENCY_IDENTITY_NOT_SUPPLIED.reason_codes == (
        DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,
    )


@pytest.mark.parametrize(
    "status",
    [
        DependencyIdentityStatus.UNRESOLVED,
        DependencyIdentityStatus.ABSENT,
        DependencyIdentityStatus.UNAVAILABLE,
    ],
)
def test_only_resolved_evidence_may_carry_identities(status) -> None:
    with pytest.raises(ValueError):
        DependencyIdentityEvidence(
            status=status,
            dependency_ids=("issue-751",),
            provenance=_PROVENANCE,
            reason_codes=("dependency-identity.declaration-unresolved",),
        )


def test_resolved_evidence_requires_provenance() -> None:
    with pytest.raises(ValueError):
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED, dependency_ids=("issue-751",)
        )


def test_status_must_be_the_canonical_enum_not_a_bare_string() -> None:
    with pytest.raises(TypeError):
        DependencyIdentityEvidence(
            status="resolved", dependency_ids=("issue-751",), provenance=_PROVENANCE
        )


# --------------------------------------------------------------------------
# Normalization: deterministic ordering, duplicates, provenance.
# --------------------------------------------------------------------------


def test_identity_ordering_is_deterministic_regardless_of_input_order() -> None:
    first = _resolved("issue-753", "issue-751", "issue-752")
    second = _resolved("issue-752", "issue-753", "issue-751")
    assert first.dependency_ids == ("issue-751", "issue-752", "issue-753")
    assert first.dependency_ids == second.dependency_ids
    assert first == second


def test_duplicates_collapse_and_record_a_truthful_reason_code() -> None:
    evidence = _resolved("issue-751", "issue-751", "issue-752")
    assert evidence.dependency_ids == ("issue-751", "issue-752")
    assert DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON in evidence.reason_codes


def test_duplicate_reason_code_is_absent_when_nothing_collapsed() -> None:
    evidence = _resolved("issue-751", "issue-752")
    assert DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON not in evidence.reason_codes


def test_surrounding_whitespace_normalizes_into_one_canonical_identity() -> None:
    evidence = _resolved("  issue-751  ", "issue-751")
    assert evidence.dependency_ids == ("issue-751",)
    assert DEPENDENCY_IDENTITY_DUPLICATE_COLLAPSED_REASON in evidence.reason_codes


def test_provenance_preserves_supplied_order_and_multiplicity() -> None:
    provenance = ("caller:b", "caller:a", "caller:b")
    evidence = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.RESOLVED,
        dependency_ids=("issue-751",),
        provenance=provenance,
    )
    assert evidence.provenance == provenance


def test_provenance_entries_are_validated_like_identities() -> None:
    for bad in ((""), ("   "), ("caller:\na",)):
        with pytest.raises((TypeError, ValueError)):
            DependencyIdentityEvidence(
                status=DependencyIdentityStatus.RESOLVED,
                dependency_ids=("issue-751",),
                provenance=bad if isinstance(bad, tuple) else (bad,),
            )


def test_reason_codes_are_deduplicated_and_deterministically_ordered() -> None:
    evidence = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.UNAVAILABLE,
        reason_codes=("z.code", "a.code", "z.code"),
    )
    assert evidence.reason_codes == ("a.code", "z.code")


def test_evidence_is_immutable() -> None:
    evidence = _resolved("issue-751")
    for attribute, value in (
        ("status", DependencyIdentityStatus.ABSENT),
        ("dependency_ids", ("issue-999",)),
        ("provenance", ("caller:other",)),
        ("reason_codes", ("x.y",)),
        ("execution_authorized", True),
        ("side_effects_performed", True),
    ):
        with pytest.raises(Exception):
            setattr(evidence, attribute, value)


# --------------------------------------------------------------------------
# Malformed identity inputs fail closed.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", "\t", "\n", "issue\n751", "issue\x00751"])
def test_malformed_and_empty_identities_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        _resolved(value)


@pytest.mark.parametrize("value", [7, 7.5, None, ["issue-751"], {"id": "issue-751"}])
def test_non_string_identities_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        _resolved(value)


@pytest.mark.parametrize("value", [True, False])
def test_boolean_like_identities_are_rejected(value: bool) -> None:
    with pytest.raises(TypeError):
        _resolved(value)


@pytest.mark.parametrize("values", ["issue-751", b"issue-751", {"issue-751": 1}, 5])
def test_identity_container_must_be_a_non_string_iterable(values: object) -> None:
    with pytest.raises(TypeError):
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED,
            dependency_ids=values,
            provenance=_PROVENANCE,
        )


# --------------------------------------------------------------------------
# Authority fields are fixed false and not caller-settable.
# --------------------------------------------------------------------------


def test_authority_fields_are_fixed_false_and_not_constructor_arguments() -> None:
    evidence = _resolved("issue-751")
    assert evidence.execution_authorized is False
    assert evidence.side_effects_performed is False
    parameters = inspect.signature(DependencyIdentityEvidence).parameters
    assert "execution_authorized" not in parameters
    assert "side_effects_performed" not in parameters


@pytest.mark.parametrize(
    "field", ["execution_authorized", "side_effects_performed"]
)
def test_serialized_authority_fields_must_be_false(field: str) -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    assert payload[field] is False
    for truthy in (True, 1, "false", None):
        with pytest.raises(ValueError):
            dependency_identity_evidence_from_dict({**payload, field: truthy})


# --------------------------------------------------------------------------
# Canonical serialization and exact reconstruction.
# --------------------------------------------------------------------------


def test_canonical_serialization_emits_every_field() -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-752", "issue-751"))
    assert payload == {
        "status": "resolved",
        "dependency_ids": ["issue-751", "issue-752"],
        "provenance": list(_PROVENANCE),
        "reason_codes": [],
        "execution_authorized": False,
        "side_effects_performed": False,
    }


@pytest.mark.parametrize(
    "evidence",
    [
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.RESOLVED,
            dependency_ids=("issue-752", "issue-751"),
            provenance=("caller:b", "caller:a"),
        ),
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.UNRESOLVED,
            provenance=_PROVENANCE,
            reason_codes=("dependency-identity.declaration-unresolved",),
        ),
        DependencyIdentityEvidence(
            status=DependencyIdentityStatus.ABSENT, provenance=_PROVENANCE
        ),
        DEPENDENCY_IDENTITY_NOT_SUPPLIED,
    ],
)
def test_exact_reconstruction_without_semantic_drift(
    evidence: DependencyIdentityEvidence,
) -> None:
    payload = dependency_identity_evidence_to_dict(evidence)
    reconstructed = dependency_identity_evidence_from_dict(payload)
    assert reconstructed == evidence
    assert reconstructed.status == evidence.status
    assert reconstructed.dependency_ids == evidence.dependency_ids
    assert reconstructed.provenance == evidence.provenance
    assert reconstructed.reason_codes == evidence.reason_codes
    assert dependency_identity_evidence_to_dict(reconstructed) == payload


def test_repeated_immutable_inputs_produce_identical_canonical_bytes() -> None:
    first = dependency_identity_evidence_to_dict(_resolved("issue-752", "issue-751"))
    second = dependency_identity_evidence_to_dict(_resolved("issue-751", "issue-752"))
    assert canonical_bytes(first) == canonical_bytes(second)


def test_unknown_fields_are_rejected_fail_closed() -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    with pytest.raises(ValueError):
        dependency_identity_evidence_from_dict({**payload, "dependency_prose": "x"})


def test_missing_fields_are_rejected_fail_closed() -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    for key in payload:
        partial = {name: value for name, value in payload.items() if name != key}
        with pytest.raises(ValueError):
            dependency_identity_evidence_from_dict(partial)


@pytest.mark.parametrize("payload", [None, [], "resolved", 5])
def test_non_mapping_payloads_are_rejected(payload: object) -> None:
    with pytest.raises(ValueError):
        dependency_identity_evidence_from_dict(payload)


@pytest.mark.parametrize("status", ["", "ready", "RESOLVED", "blocked", 5, True, None])
def test_unsupported_serialized_status_is_rejected(status: object) -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    with pytest.raises(ValueError):
        dependency_identity_evidence_from_dict({**payload, "status": status})


@pytest.mark.parametrize(
    "field", ["dependency_ids", "provenance", "reason_codes"]
)
def test_serialized_sequences_must_be_lists(field: str) -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    with pytest.raises(ValueError):
        dependency_identity_evidence_from_dict({**payload, field: "issue-751"})


def test_serialized_identities_are_revalidated_on_reconstruction() -> None:
    payload = dependency_identity_evidence_to_dict(_resolved("issue-751"))
    for bad in ([""], [True], [7], ["issue\n751"]):
        with pytest.raises((TypeError, ValueError)):
            dependency_identity_evidence_from_dict(
                {**payload, "dependency_ids": bad}
            )


# --------------------------------------------------------------------------
# Producer boundary: no prose parsing, no write-capable dependency.
# --------------------------------------------------------------------------


def _imported_modules(module) -> set[str]:
    """Return every module name imported by ``module``, resolved statically."""
    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            names.add(f"{prefix}{node.module or ''}")
    return names


_ALLOWED_STAGE_MODEL_IMPORTS = {
    "__future__",
    "hashlib",
    "json",
    "collections.abc",
    "dataclasses",
    "enum",
    "typing",
    "scripts.agent_os_issue_acceptance.acceptance_report_transport",
    "scripts.agent_os_issue_acceptance.issueplan_current_state",
    "scripts.agent_os_issue_acceptance.readiness",
}

_ALLOWED_READINESS_STAGE_IMPORTS = {
    "__future__",
    "scripts.agent_os_issue_acceptance.issueplan_current_state",
    "scripts.agent_os_issue_acceptance.issueplan_scanner",
    "scripts.agent_os_issue_acceptance.models",
    "scripts.agent_os_issue_acceptance.readiness",
    ".source_stage",
    ".stage_models",
}


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        (stage_models, _ALLOWED_STAGE_MODEL_IMPORTS),
        (readiness_stage, _ALLOWED_READINESS_STAGE_IMPORTS),
    ],
)
def test_no_write_capable_or_external_dependency_is_reachable(
    module, allowed: set[str]
) -> None:
    """Neither module may reach a network, subprocess, Git, or provider path."""
    unexpected = _imported_modules(module) - allowed
    assert not unexpected, f"{module.__name__} gained imports: {sorted(unexpected)}"


def test_evidence_model_exposes_no_io_shaped_member() -> None:
    members = {
        name for name in dir(DependencyIdentityEvidence) if not name.startswith("_")
    }
    assert not any(
        name.startswith(prefix)
        for name in members
        for prefix in ("write", "create", "update", "delete", "post", "read", "fetch")
    ), f"DependencyIdentityEvidence exposes an I/O-shaped member: {members}"


def test_identities_enter_only_through_one_structured_keyword_argument() -> None:
    parameters = inspect.signature(readiness_stage.prepare_issue_readiness).parameters
    identity_parameter = parameters["dependency_identity_evidence"]
    assert identity_parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert identity_parameter.default is None
    assert identity_parameter.annotation == "DependencyIdentityEvidence | None"
