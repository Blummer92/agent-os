"""#3690 CR-1/CR-1B: shared satisfaction validation and serializer, distinct outputs.

``lifecycle_reconciliation`` and ``closure_admission_actions`` previously held
copies of the #3680 satisfaction-snapshot validator with identical validation
rules and messages (the closure copy lacked only the read-only
``unsatisfied_criteria`` property). CR-1 moves
that validation core into ``satisfaction_snapshot``; CR-1B shares the
serializer while retaining each consumer's trust boundary and output shape. These tests prove:

1. the existing acceptance/rejection corpus holds against the shared core;
2. the closure receipt block never carries ``closure_ready``;
3. the reconciliation reporting block keeps ``closure_ready``;
4. receipt ids and serialized reconciliation bytes are identical to the
   pre-consolidation values recorded on ``main`` a3a396b0;
5. malformed and foreign evidence stays rejected;
6. the shared core keeps the architecture dependency direction; and
7. the duplication is actually gone (one definition, consumer aliases only).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance import (
    closure_admission_actions as closure_module,
)
from scripts.agent_os_issue_acceptance import (
    lifecycle_reconciliation as reconciliation_module,
)
from scripts.agent_os_issue_acceptance import satisfaction_snapshot as shared
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    evaluate_issue_closure,
    verify_closure_admission_receipt,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_reconciliation import (
    reconcile_lifecycle,
    serialize_lifecycle_reconciliation_input,
    serialize_lifecycle_reconciliation_result,
)
from tests.agent_os_issue_acceptance.test_3680_satisfaction_closure_integration import (
    BAD_SNAPSHOTS,
    CONSISTENCY_CORPUS,
    closure_request,
    closure_snapshot,
    complete_snapshot,
    complete_snapshot_for,
    incomplete_snapshot,
    incomplete_snapshot_for,
    manual_review_snapshot,
    merged_input,
    snapshot,
    stale_snapshot,
)

PACKAGE = Path(__file__).resolve().parents[2] / "scripts" / "agent_os_issue_acceptance"


def _sha256(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 1. The existing corpus, run directly against the shared core.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CONSISTENCY_CORPUS))
def test_corpus_outcome_against_shared_core(name):
    value = copy.deepcopy(CONSISTENCY_CORPUS[name])
    if name in BAD_SNAPSHOTS:
        with pytest.raises((TypeError, ValueError)):
            shared.validate_satisfaction_snapshot(value)
        return
    parsed = shared.validate_satisfaction_snapshot(value)
    assert type(parsed) is shared.SatisfactionSnapshot
    assert parsed.status == CONSISTENCY_CORPUS[name]["status"]
    assert parsed.complete is (CONSISTENCY_CORPUS[name]["status"] == "complete")


def test_corpus_contains_valid_and_adversarial_cases():
    # Guards against a vacuous corpus: every bad case is in it.
    assert set(BAD_SNAPSHOTS) <= set(CONSISTENCY_CORPUS)
    assert len(BAD_SNAPSHOTS) >= 20
    assert len(set(CONSISTENCY_CORPUS) - set(BAD_SNAPSHOTS)) >= 5


# ---------------------------------------------------------------------------
# 2./3. Distinct serialized output shapes.
# ---------------------------------------------------------------------------


def test_closure_receipt_block_excludes_closure_ready():
    receipt = evaluate_issue_closure(
        closure_request(satisfaction=complete_snapshot_for(3432)),
        closure_snapshot(),
    )
    assert set(receipt["satisfaction"]) == shared.SATISFACTION_KEYS
    assert tuple(receipt["satisfaction"]) == (
        "repository", "issue_number", "issue_body_digest", "status", "criteria",
    )
    assert "closure_ready" not in receipt["satisfaction"]
    # The closure block round-trips through the shared validator exactly.
    assert receipt["satisfaction"] == complete_snapshot_for(3432)


def test_reconciliation_block_keeps_closure_ready():
    for value, expected in (
        (complete_snapshot(), True),
        (incomplete_snapshot(), False),
        (stale_snapshot(), False),
        (manual_review_snapshot(), False),
    ):
        block = reconcile_lifecycle(merged_input(value)).to_dict()["satisfaction"]
        assert set(block) == shared.SATISFACTION_KEYS | {"closure_ready"}
        assert tuple(block) == (
            "repository", "issue_number", "issue_body_digest", "status",
            "closure_ready", "criteria",
        )
        assert block["closure_ready"] is expected


def test_reconciliation_block_is_not_a_closure_snapshot():
    # The serializers are intentionally not interchangeable: the reporting
    # block's closure_ready key fails the closure validator's exact key set,
    # so a reconciliation block can never be cited as a closure receipt block.
    block = reconcile_lifecycle(merged_input(complete_snapshot())).to_dict()[
        "satisfaction"
    ]
    with pytest.raises(ValueError, match="keys must be exactly"):
        closure_module._satisfaction_snapshot(block)


def test_receipt_with_reconciliation_block_never_verifies():
    request = closure_request(satisfaction=complete_snapshot_for(3432))
    snap = closure_snapshot()
    receipt = evaluate_issue_closure(request, snap)
    receipt["satisfaction"] = {**receipt["satisfaction"], "closure_ready": True}
    authorization = produce_lifecycle_mutation_authorization(request.decision, snap)
    assert (
        verify_closure_admission_receipt(
            receipt,
            authorization=authorization,
            fresh_snapshot=snap,
            acceptance=request.acceptance,
        )
        is False
    )


# ---------------------------------------------------------------------------
# 4. Byte identity with the pre-consolidation implementation.
#
# Values recorded by running these exact fixtures on main a3a396b0 before
# the consolidation: (receipt_id, sha256 of the canonical receipt JSON) and
# (sha256 of the serialized reconciliation input, sha256 of the serialized
# reconciliation result).
# ---------------------------------------------------------------------------

_CLOSURE_GOLDEN = {
    # Receipt ids are unchanged from pre-consolidation: the hashed core
    # excludes the reconciliation contract. Whole-receipt digests below
    # were re-recorded for #3489 because the receipt now also carries
    # post_close_reconciliation_contract; stripping that one field from a
    # receipt reproduces the old digest exactly, so the re-recording
    # records only the added field, not a changed id or core.
    "none": (
        "closure-admission-receipt:4e5923c98a0baf93f44c1a663e613e02afe67f88b59c3525d0b8cabf9efaf1e1",
        "400c3f606b64e2429339432748bacb8a22460f28bfe8d3733c3785a03cfe9ae1",
    ),
    "complete": (
        "closure-admission-receipt:72c2c0cc4472c9d249f0d664421d9f1fde3b17abcb9829ec76a557602882cafa",
        "d370afe3cec51a56c6eb3c15453fe379c26b647849f7667fd2b594f4de359758",
    ),
    "incomplete": (
        "closure-admission-receipt:c9592f86e252dab767164e1d8419c39900b3907aeb0b89d27da6d55793a06ecb",
        "63ef9cb90aa729d5c1f96ca1c922fc4540ab129ad62419573bdec2d54628862a",
    ),
    "manual-review-empty": (
        "closure-admission-receipt:335532da59a4721d639b48c514ed6771a0f491046f990c3c88b308123d1ff480",
        "1004b26e93a306755cfe2763a69bc6068bd82494c743909ab2d60d7f9f99334f",
    ),
}

_RECONCILIATION_GOLDEN = {
    ("none", False): (
        "f34601c7cbc8796cd752e3fc3db42c4e19c9a0f7017a3e0c27ef5e1e92ec8bab",
        "5dcc1ca3c912b108c4cbccc64cd2a512ceb7f7e6169f29662aa132cd1a442b6b",
    ),
    ("none", True): (
        "56e1a7bcf713fc080594a59dce2ca1e63ce934e74d40d30311fd4aae258f8950",
        "7062d84fa0f2a35f2a15f2f0432e6088936ea781bd70be405306ecdd8738527f",
    ),
    ("complete", False): (
        "10b81a147cb71e4b262dc4470c9a3b7c006dbd7bf22fa3d33b1166c1a263354a",
        "2d1ea76bb628a4447eb6ff046ce5d715f93ad65c71b1fe3fdb7afaf7a3126aed",
    ),
    ("complete", True): (
        "50b166c33e6e98b2faaeaa5e6e12e144fe4cdd7080993035ed543cd0a5c3ed81",
        "dff8a122b02507cc14d2343360ba2f6c9ca243207e31bd82bd45374766546116",
    ),
    ("incomplete", False): (
        "0043b359c3e23929180d0f5a895c8617b0d2c5795cc6fe06c20bb8d161b381db",
        "6ea21138c0e210cdcab487dd02595aa5ad05029f516f0e65f2f8a229e2475849",
    ),
    ("incomplete", True): (
        "47ba8c7056efbbe0afa80f67b8f6662ebe925b49c34eb4490b581bb9a79414ff",
        "60d919daf14334f33ad248ee569e25ccf29d3d27c468e69296b61c0dd1c86a23",
    ),
    ("stale", False): (
        "0c0675bcf8490cbe3cf0267452db7b3fd7d35e70395cd2a508940be07d232cd4",
        "687af325de664c3c2e2f5d61d25db67e1940c0b097d4288fbe7ce43bbd7e3ac8",
    ),
    ("stale", True): (
        "13e504e934b25312b26f2ab1ccfa3f681c484a824140dd2cebda9d33745d5532",
        "aae0f6989ae4d1e510e110e2144d97bf703ca2958db4fd19ac855aab206d7f96",
    ),
    ("manual-review", False): (
        "02edca5af0517042a2c7ab2ed69e5d6b6039e54e4b2760fb32274c51e97fc64d",
        "7d38b73798af9af25dd555ba5717668caf6d9ee1b7398405d9cb1173b0e6f324",
    ),
    ("manual-review", True): (
        "e1d5e7563f4d51d308a81f4e0bbdcfb668377505c78c32ff0a02f893f8716431",
        "83a86bb444c24815eb81934d07caf12858dabbb9a42eb674c63a7ce0c2efd36b",
    ),
}


def _closure_case(name):
    return {
        "none": None,
        "complete": complete_snapshot_for(3432),
        "incomplete": incomplete_snapshot_for(3432),
        "manual-review-empty": snapshot("manual-review", [], issue_number=3432),
    }[name]


def _reconciliation_case(name):
    return {
        "none": None,
        "complete": complete_snapshot(),
        "incomplete": incomplete_snapshot(),
        "stale": stale_snapshot(),
        "manual-review": manual_review_snapshot(),
    }[name]


@pytest.mark.parametrize("name", sorted(_CLOSURE_GOLDEN))
def test_closure_receipt_bytes_identical_to_pre_consolidation(name):
    receipt = evaluate_issue_closure(
        closure_request(satisfaction=_closure_case(name)), closure_snapshot()
    )
    receipt_id, receipt_digest = _CLOSURE_GOLDEN[name]
    assert receipt["receipt_id"] == receipt_id
    assert (
        _sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        == receipt_digest
    )


@pytest.mark.parametrize("key", sorted(_RECONCILIATION_GOLDEN))
def test_reconciliation_bytes_identical_to_pre_consolidation(key):
    name, with_authority = key
    reconciliation_input = merged_input(
        _reconciliation_case(name), with_authority=with_authority
    )
    result = reconcile_lifecycle(reconciliation_input)
    input_digest, result_digest = _RECONCILIATION_GOLDEN[key]
    assert _sha256(serialize_lifecycle_reconciliation_input(reconciliation_input)) == (
        input_digest
    )
    assert _sha256(serialize_lifecycle_reconciliation_result(result)) == result_digest


# ---------------------------------------------------------------------------
# 5. Malformed and foreign evidence stays rejected at both consumers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(BAD_SNAPSHOTS))
def test_bad_snapshot_rejected_by_shared_core_and_both_consumers(name):
    with pytest.raises((TypeError, ValueError)):
        shared.validate_satisfaction_snapshot(copy.deepcopy(BAD_SNAPSHOTS[name]))
    with pytest.raises((TypeError, ValueError)):
        merged_input(copy.deepcopy(BAD_SNAPSHOTS[name]))
    with pytest.raises((TypeError, ValueError)):
        closure_request(satisfaction=copy.deepcopy(BAD_SNAPSHOTS[name]))


def test_cross_issue_evidence_rejected_by_both_consumers():
    with pytest.raises(ValueError, match="identity does not match"):
        merged_input(complete_snapshot_for(3432))
    with pytest.raises(ValueError, match="identity does not match"):
        closure_request(satisfaction=complete_snapshot())


# ---------------------------------------------------------------------------
# 6. Architecture: the shared core is a leaf (stdlib only).
# ---------------------------------------------------------------------------


def test_shared_core_imports_only_the_standard_library():
    tree = ast.parse((PACKAGE / "satisfaction_snapshot.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "shared core must not import package modules"
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"__future__", "dataclasses"}


# ---------------------------------------------------------------------------
# 7. The duplication is gone.
# ---------------------------------------------------------------------------

_CORE_NAMES = (
    "_derived_satisfaction_status",
    "_SatisfactionCriterionSnapshot",
    "_SatisfactionSnapshot",
    "_satisfaction_snapshot",
)


@pytest.mark.parametrize("module", [reconciliation_module, closure_module])
def test_consumers_alias_the_shared_core(module):
    assert module._SatisfactionSnapshot is shared.SatisfactionSnapshot
    assert module._SatisfactionCriterionSnapshot is shared.SatisfactionCriterionSnapshot
    assert module._satisfaction_snapshot is shared.validate_satisfaction_snapshot
    assert module.satisfaction_block is shared.satisfaction_block


@pytest.mark.parametrize(
    "filename", ["lifecycle_reconciliation.py", "closure_admission_actions.py"]
)
def test_consumers_define_no_local_validation_core(filename):
    tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert not defined & set(_CORE_NAMES)
    assert not defined & {
        "validate_satisfaction_snapshot",
        "SatisfactionSnapshot",
        "SatisfactionCriterionSnapshot",
        "derived_satisfaction_status",
    }
    # The two local serializers have been removed; consumers import the shared one.
    assert "_satisfaction_block" not in defined
