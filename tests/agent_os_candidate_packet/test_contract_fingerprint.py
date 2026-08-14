"""Focused AOS-AUTO1G tests for the deterministic implementation-contract fingerprint (#1105)."""

from __future__ import annotations

import re

import pytest

from scripts.agent_os_candidate_packet.contract_fingerprint import (
    IMPLEMENTATION_CONTRACT_SCHEMA_NAME,
    IMPLEMENTATION_CONTRACT_SCHEMA_VERSION,
    ImplementationContractError,
    compute_implementation_contract_fingerprint,
    derive_canonical_contract,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import IssueReadinessStageRequest
from tests.agent_os_candidate_packet.test_readiness_stage import (
    _FakeIssueReader,
    _FakeRepositoryReader,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _contract(**overrides) -> dict[str, object]:
    values = dict(
        entity_id="issue-1105-fixture",
        allowed_files=("scripts/agent_os_candidate_packet",),
        forbidden_paths=(".github/workflows",),
        required_tests=("tests/agent_os_candidate_packet",),
        documentation_impact="docs-not-required",
    )
    values.update(overrides)
    return values


# --------------------------------------------------------------------------
# 1. Determinism and shape.
# --------------------------------------------------------------------------


def test_fingerprint_is_a_bare_hex64_digest() -> None:
    fingerprint = compute_implementation_contract_fingerprint(canonical_contract=_contract())

    assert _HEX64.fullmatch(fingerprint)
    assert not fingerprint.startswith("implementation-contract:")


def test_identical_normalized_semantics_produce_identical_fingerprint() -> None:
    first = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    second = compute_implementation_contract_fingerprint(canonical_contract=_contract())

    assert first == second


def test_caller_ordering_and_duplicates_do_not_change_the_fingerprint() -> None:
    """Scope/test membership is order- and duplicate-independent."""
    baseline = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(allowed_files=("a.py", "b.py"))
    )
    reordered = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(allowed_files=("b.py", "a.py"))
    )
    duplicated = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(allowed_files=("a.py", "b.py", "a.py"))
    )

    assert baseline == reordered == duplicated


# --------------------------------------------------------------------------
# 2. Semantic movement changes the fingerprint.
# --------------------------------------------------------------------------


def test_scope_movement_changes_the_fingerprint() -> None:
    baseline = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    moved = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(allowed_files=("scripts/other_package",))
    )

    assert baseline != moved


def test_forbidden_path_movement_changes_the_fingerprint() -> None:
    baseline = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    moved = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(forbidden_paths=("00_Governance",))
    )

    assert baseline != moved


def test_required_test_movement_changes_the_fingerprint() -> None:
    baseline = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    moved = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(required_tests=("tests/other_package",))
    )

    assert baseline != moved


def test_entity_id_movement_changes_the_fingerprint() -> None:
    baseline = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    moved = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(entity_id="issue-9999-different")
    )

    assert baseline != moved


def test_documentation_impact_movement_changes_the_fingerprint() -> None:
    baseline = compute_implementation_contract_fingerprint(canonical_contract=_contract())
    moved = compute_implementation_contract_fingerprint(
        canonical_contract=_contract(documentation_impact="docs-required")
    )

    assert baseline != moved


# --------------------------------------------------------------------------
# 3. Non-semantic movement never changes the fingerprint (proven at the
#    derivation boundary: two governed-field snapshots that differ only in
#    unrelated prose/labels/timestamps/owner fields yield the same contract).
# --------------------------------------------------------------------------


def _readiness_for_body(body: str, *, expected_source_revision=None):
    request = IssueReadinessStageRequest(
        repository="Blummer92/agent-os",
        issue_number=750,
        observed_at="2026-08-14T00:00:00Z",
        freshness_boundary="stage-observation",
        expected_source_revision=expected_source_revision,
    )
    reader = _FakeIssueReader(item={**_FakeIssueReader().read_issue("x", 1).item, "body": body})
    return prepare_issue_readiness(request, reader, _FakeRepositoryReader())


def test_unrelated_prose_and_labels_do_not_change_the_fingerprint() -> None:
    """Two bodies with identical governed fields but different surrounding prose."""
    yaml_block = """
```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-shared
  owner_agent: candidate-packet-agent
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - scripts/agent_os_candidate_packet
  forbidden_paths: []
  required_tests: []
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: none needed
```
"""
    body_a = "Some prose about the change.\n" + yaml_block
    body_b = "Totally different unrelated prose, formatting, and commentary.\n\n\n" + yaml_block

    readiness_a = _readiness_for_body(body_a)
    readiness_b = _readiness_for_body(body_b)
    contract_a = derive_canonical_contract(
        readiness_a.issueplan_current_state_evidence.source_snapshot
    )
    contract_b = derive_canonical_contract(
        readiness_b.issueplan_current_state_evidence.source_snapshot
    )

    fingerprint_a = compute_implementation_contract_fingerprint(canonical_contract=contract_a)
    fingerprint_b = compute_implementation_contract_fingerprint(canonical_contract=contract_b)

    assert fingerprint_a == fingerprint_b
    # But the raw source/body revision *does* differ -- proving it is bound
    # to prose movement while the contract fingerprint is not.
    assert readiness_a.snapshot.source_revision != readiness_b.snapshot.source_revision


def test_owner_agent_and_source_of_truth_are_excluded_from_the_contract() -> None:
    """These already have their own binding into the #751 planning node."""
    contract = derive_canonical_contract(
        _readiness_for_body(
            """
```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-owner-exclusion
  owner_agent: someone-else
  source_of_truth: elsewhere
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: none needed
```
"""
        ).issueplan_current_state_evidence.source_snapshot
    )

    assert "owner_agent" not in contract
    assert "source_of_truth" not in contract


# --------------------------------------------------------------------------
# 4. Source revision remains a separate, independent identity.
# --------------------------------------------------------------------------


def test_source_revision_is_never_replaced_by_the_contract_fingerprint() -> None:
    readiness = _readiness_for_body(
        """
```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-independent-identity
  owner_agent: candidate-packet-agent
  source_of_truth: GitHub
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: none needed
```
"""
    )
    contract = derive_canonical_contract(
        readiness.issueplan_current_state_evidence.source_snapshot
    )
    fingerprint = compute_implementation_contract_fingerprint(canonical_contract=contract)

    assert readiness.snapshot.source_revision.startswith("github-issue-v1:")
    assert readiness.snapshot.source_revision != fingerprint
    assert _HEX64.fullmatch(fingerprint)
    assert not _HEX64.fullmatch(readiness.snapshot.source_revision)


# --------------------------------------------------------------------------
# 5 & 6. Malformed, incomplete, oversized, and type-confused input fails closed.
# --------------------------------------------------------------------------


def test_missing_fields_fail_closed() -> None:
    with pytest.raises(ImplementationContractError, match="missing field"):
        compute_implementation_contract_fingerprint(canonical_contract={"entity_id": "x"})


def test_unsupported_fields_fail_closed() -> None:
    with pytest.raises(ImplementationContractError, match="unsupported field"):
        compute_implementation_contract_fingerprint(
            canonical_contract={**_contract(), "surprise": "value"}
        )


def test_non_mapping_input_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="mapping"):
        compute_implementation_contract_fingerprint(canonical_contract=["not", "a", "mapping"])


def test_boolean_for_string_type_confusion_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="entity_id must be a string"):
        compute_implementation_contract_fingerprint(canonical_contract=_contract(entity_id=True))


def test_boolean_in_list_field_fails_closed() -> None:
    with pytest.raises(ImplementationContractError):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(allowed_files=(True,))
        )


def test_non_string_scalar_fails_closed() -> None:
    with pytest.raises(ImplementationContractError):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(documentation_impact=123)
        )


def test_non_iterable_list_field_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="iterable"):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(required_tests=123)
        )


def test_string_as_list_field_fails_closed() -> None:
    """A bare string is iterable but must not be silently treated as a one-item scope."""
    with pytest.raises(ImplementationContractError, match="iterable"):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(allowed_files="scripts/agent_os_candidate_packet")
        )


def test_empty_string_item_fails_closed() -> None:
    with pytest.raises(ImplementationContractError):
        compute_implementation_contract_fingerprint(canonical_contract=_contract(entity_id=""))


def test_control_character_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="control characters"):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(entity_id="issue\x00-bad")
        )


def test_oversized_list_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="maximum item count"):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(
                allowed_files=tuple(f"path-{i}.py" for i in range(2_001))
            )
        )


def test_oversized_text_fails_closed() -> None:
    with pytest.raises(ImplementationContractError, match="maximum length"):
        compute_implementation_contract_fingerprint(
            canonical_contract=_contract(entity_id="x" * 4_097)
        )


def test_derive_canonical_contract_rejects_wrong_type() -> None:
    with pytest.raises(ImplementationContractError, match="IssuePlanSourceSnapshot"):
        derive_canonical_contract("not-a-snapshot")


def test_schema_constants_are_stable() -> None:
    assert IMPLEMENTATION_CONTRACT_SCHEMA_NAME == "agent-os-implementation-contract"
    assert IMPLEMENTATION_CONTRACT_SCHEMA_VERSION == "1.0"
