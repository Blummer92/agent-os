"""Structural tests for the LP4 implementation handoff (issue #649).

#649 says issue text alone authorizes no branch, code, tests, or pull request; a
separate handoff must supply the main SHA, contract sources, CW5A reuse location,
file allowlist, validation commands, and delivery requirements first.

These tests prove the handoff stays unauthorized while its gates are open, that
every claim it makes about another artifact is true of that artifact right now --
the CW5A symbols it names really are exported, the contract versions it cites
really match the registries, the counts it asserts really are the ratified counts
-- and that its file allowlist cannot reach into CW5A and build a second core.
"""

from __future__ import annotations

import pytest
import yaml

from tests.lp_contract_support import (
    ROOT,
    assert_canonical_serialization_is_stable,
    assert_contract_identity,
    assert_no_forbidden_governed_keys,
    assert_normative_ids_match_anchors,
    assert_standards_exist,
    load_registry,
    load_yaml_text,
    read_text,
)

REGISTRY_PATH = "04_Registry/lp4-implementation-handoff.yaml"
CW5A_PACKAGE = "src/instructional_workflow_contracts"

TOP_LEVEL_KEYS = (
    "registry_name",
    "contract_version",
    "record_revision",
    "normative_standard",
    "target_issue",
    "parent_roadmap",
    "handoff_state",
    "implementation_authorized",
    "required_main_sha",
    "required_main_sha_status",
    "gates",
    "contract_sources",
    "issue_ratified_references",
    "module_versions",
    "cw5a_reuse",
    "prohibited_reimplementation",
    "interface_gaps",
    "file_allowlist",
    "conformance_requirements",
    "scope_rules",
    "validation_commands",
    "exact_head_evidence",
    "delivery",
    "issue_text_corrections",
    "non_authority_confirmation",
)

REQUIRED_VALIDATION_PHASES = frozenset(
    {
        "focused",
        "focused-fail-fast",
        "contract-conformance",
        "reuse-and-import-isolation",
        "structural",
        "aggregate",
    }
)

REQUIRED_CORRECTIONS = frozenset(
    {"demand-dimension-count", "non-authority-field-set", "unnamed-packet-fields"}
)


def _registry() -> dict:
    return load_registry(REGISTRY_PATH)


def _cw5a_exported_names() -> set[str]:
    """Parse CW5A's __all__ without importing it, so this test needs no PYTHONPATH."""
    import ast

    tree = ast.parse(read_text(f"{CW5A_PACKAGE}/__init__.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return {element.value for element in node.value.elts}
    raise AssertionError("CW5A __init__.py declares no __all__")


def _count(document: dict, registry_key: str, count_basis: str) -> int:
    entry = document[registry_key]
    if count_basis == "all":
        return len(entry)
    if count_basis == "non-authority":
        return sum(1 for field in entry if field["kind"] == "non-authority")
    if count_basis == "non-null-default":
        return sum(1 for field in entry if field["default"] is not None)
    if count_basis == "active":
        return sum(1 for record in entry if not record["deprecated"])
    raise AssertionError(f"unknown count_basis: {count_basis}")


def _validate_contract(document: dict) -> None:
    """Every invariant a conforming handoff must satisfy."""
    assert tuple(document) == TOP_LEVEL_KEYS
    assert_contract_identity(document, registry_name="lp4-implementation-handoff")
    assert_standards_exist([document["normative_standard"]])
    assert_normative_ids_match_anchors(document, [document["normative_standard"]])
    assert_no_forbidden_governed_keys(document)

    assert document["target_issue"] == 649
    assert document["handoff_state"] == "prepared-not-authorized"
    assert document["implementation_authorized"] is False

    # The merge gate and the SHA claim must agree. A handoff may not name a main
    # SHA while the contracts it depends on are absent from main.
    gates = {gate["id"]: gate for gate in document["gates"]}
    assert len(gates) == len(document["gates"])
    for gate in gates.values():
        assert gate["owner"], f"{gate['id']} names no owner"
        assert gate["detail"], f"{gate['id']} records no detail"
    merged = gates["lp-contracts-merged-to-main"]["satisfied"]
    if merged:
        assert document["required_main_sha"], "merged contracts require a named main SHA"
        assert document["required_main_sha_status"] == "resolved"
    else:
        assert document["required_main_sha"] is None
        assert document["required_main_sha_status"] == "pending-lp-contract-merge"

    # An open gate must keep the handoff unauthorized.
    if any(not gate["satisfied"] for gate in gates.values()):
        assert document["implementation_authorized"] is False

    for source in document["contract_sources"]:
        if source["kind"] != "repository-file":
            continue
        assert_standards_exist([source["registry"], *source["standards"]])
        cited = load_registry(source["registry"])
        assert cited["contract_version"] == source["contract_version"], (
            f"{source['id']} cites a version the registry does not carry"
        )
        assert cited["record_revision"] == source["record_revision"]

    for reference in document["issue_ratified_references"]:
        assert type(reference["issue"]) is int
        assert reference["scope"]

    reuse = document["cw5a_reuse"]
    assert_standards_exist(reuse["modules"])
    exported = _cw5a_exported_names()
    for group in reuse["consumed_symbols"]:
        assert group["symbols"], f"{group['concern']} names no symbol"
        missing = sorted(set(group["symbols"]) - exported)
        assert not missing, f"{group['concern']} names non-exported CW5A symbols: {missing}"

    # LP4 must not edit CW5A itself; that is where a second core would be hidden.
    allowlist = [entry["path"] for entry in document["file_allowlist"]]
    assert len(allowlist) == len(set(allowlist))
    for path in allowlist:
        assert not path.startswith(CW5A_PACKAGE), f"{path} reaches into the shared core"
        assert entry_purpose(document, path), f"{path} states no purpose"

    for gap in document["interface_gaps"]:
        assert gap["symbol"] and gap["requirement"] and gap["observed"]
        assert gap["smallest_sufficient_change"]
        assert gap["resolution_owner"]

    for requirement in document["conformance_requirements"]:
        cited = next(
            source for source in document["contract_sources"]
            if source["id"] == requirement["derived_from"]
        )
        registry = load_registry(cited["registry"])
        actual = _count(registry, requirement["registry_key"], requirement["count_basis"])
        assert actual == requirement["expected_count"], (
            f"{requirement['id']} expects {requirement['expected_count']} "
            f"but the ratified registry has {actual}"
        )

    phases = {command["phase"] for command in document["validation_commands"]}
    assert REQUIRED_VALIDATION_PHASES <= phases
    for command in document["validation_commands"]:
        assert command["command"].strip()

    assert document["exact_head_evidence"]["github_sha_may_be_labelled_branch_head"] is False
    assert document["exact_head_evidence"]["required_fields"]

    delivery = document["delivery"]
    assert delivery["draft_pull_request"] is True
    assert delivery["one_branch_only"] is True
    assert_standards_exist([delivery["final_report_standard"]])

    corrections = {item["id"] for item in document["issue_text_corrections"]}
    assert REQUIRED_CORRECTIONS <= corrections
    for item in document["issue_text_corrections"]:
        assert item["decision"] and item["consequence_if_uncorrected"]

    confirmation = document["non_authority_confirmation"]
    for key in (
        "external_system_access",
        "network_access",
        "credential_use",
        "model_invocation",
        "real_student_data",
    ):
        assert confirmation[key] is False, f"{key} must be false"
    assert confirmation["fixtures_are_synthetic"] is True


def entry_purpose(document: dict, path: str) -> str:
    return next(entry["purpose"] for entry in document["file_allowlist"] if entry["path"] == path)


def test_handoff_is_consistent_with_every_artifact_it_cites() -> None:
    _validate_contract(_registry())


def test_canonical_serialization_is_stable() -> None:
    assert_canonical_serialization_is_stable(_registry())


def test_handoff_authorizes_nothing_while_gates_are_open() -> None:
    document = _registry()
    assert any(not gate["satisfied"] for gate in document["gates"])
    assert document["implementation_authorized"] is False
    assert document["required_main_sha"] is None


def test_lp_reason_namespace_gap_is_recorded_and_still_real() -> None:
    """The recorded gap must stay true; if CW5A is fixed, the record must be updated."""
    import re

    gap = next(
        item for item in _registry()["interface_gaps"]
        if item["id"] == "lp-reason-namespace-rejected"
    )
    assert gap["resolved_in_this_handoff"] is False

    common = read_text(f"{CW5A_PACKAGE}/common.py")
    pattern = re.search(r"_REASON_RE = re\.compile\(\s*\n?\s*r\"([^\"]+)\"", common)
    assert pattern, "could not locate the CW5A reason pattern"
    assert not re.match(pattern.group(1), "lp-pacing-time-budget-missing"), (
        "CW5A now accepts lp-* codes; the recorded interface gap is stale"
    )


def test_allowlist_does_not_collide_with_existing_packages() -> None:
    for entry in _registry()["file_allowlist"]:
        assert not (ROOT / entry["path"]).exists(), (
            f"{entry['path']} already exists; the allowlist would overwrite it"
        )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("record_revision: 1", "record_revision: 1\nrecord_revision: 2"),
        ("gates:", "alias_source: &shared value\nalias_copy: *shared\ngates:"),
        ("gates:", "merged: {<<: {value: bad}}\ngates:"),
        ("gates:", "tagged: !custom bad\ngates:"),
        ("record_revision: 1", "record_revision: 1.5"),
    ],
)
def test_hostile_yaml_documents_fail_closed(old: str, new: str) -> None:
    text = read_text(REGISTRY_PATH).replace(old, new, 1)
    with pytest.raises((AssertionError, ValueError, yaml.YAMLError)):
        _validate_contract(load_yaml_text(text))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # The handoff authorizing itself while gates are open.
        ("implementation_authorized: false", "implementation_authorized: true"),
        ("handoff_state: prepared-not-authorized", "handoff_state: authorized"),
        # Naming a main SHA that does not carry the contracts.
        ("required_main_sha: null", "required_main_sha: 797429ef13f72f7a17597b2e520b2c039f374e32"),
        # Drifting back to five dimensions.
        ("    count_basis: all\n    expected_count: 6", "    count_basis: all\n    expected_count: 5"),
        # Dropping three non-authority flags, as #649 currently does.
        ("    count_basis: non-authority\n    expected_count: 10", "    count_basis: non-authority\n    expected_count: 7"),
        # Citing a CW5A symbol that is not exported.
        ("        - canonical_json_bytes", "        - canonical_json_writer"),
        # Reaching into the shared core.
        ("  - path: src/instructional_pacing/packet.py", "  - path: src/instructional_workflow_contracts/pacing.py"),
        # Silently claiming no external system while enabling network access.
        ("  network_access: false", "  network_access: true"),
    ],
)
def test_authorization_and_accuracy_violations_are_rejected(old: str, new: str) -> None:
    base = read_text(REGISTRY_PATH)
    text = base.replace(old, new, 1)
    assert text != base, "mutation did not apply"
    with pytest.raises((AssertionError, ValueError, KeyError, StopIteration)):
        _validate_contract(load_yaml_text(text))
