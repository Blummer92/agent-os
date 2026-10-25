"""Production-caller connection tests (#3463).

Proves the exact sequence the production ``merge_admission`` workflow job
runs, in process and without mocks for the canonical evaluator:

1. ``merge_admission_actions`` (candidate front door) on a fixed transport
   returns a blocked candidate receipt with ``merge_authorized is False``.
2. ``merge_applicability`` on the SAME transport and the SAME fake GitHub
   surface returns an applicable dispatch receipt with
   ``merge_authorized is True`` only because the canonical evaluator
   returned applicable for the native merge-specific v1.2 record.
3. A transport the candidate step blocks (wrong merge method) is blocked
   by dispatch too, with canonical applicability NOT evaluated — the
   dispatch consumer cannot bypass its own front door.

No test here performs a merge; the fake GitHub surface is read-only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_issue_acceptance import merge_admission_actions as actions  # noqa: E402
from scripts.agent_os_issue_acceptance.merge_applicability import (  # noqa: E402
    evaluate_merge_dispatch_applicability,
)

_HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    "_tdispatch", _HERE / "test_merge_applicability.py"
)
_tdispatch = importlib.util.module_from_spec(_spec)
sys.modules["_tdispatch"] = _tdispatch
_spec.loader.exec_module(_tdispatch)


def _client_and_transport(**transport_changes):
    bundle = _tdispatch._tauth._bundle()
    record = _tdispatch._authorized_record(bundle)
    pr = _tdispatch._PR()
    comments = _tdispatch._comments_for(bundle, record)
    client = _tdispatch._Client(_tdispatch._Repo(pr, comments))
    return client, _tdispatch._transport(**transport_changes)


def test_production_sequence_candidate_then_dispatch_reaches_canonical():
    client, transport = _client_and_transport()
    candidate = actions.evaluate_merge_admission_transport(
        transport, repository=_tdispatch.REPO, github_client=client,
        evaluated_at=_tdispatch.NOW,
    )
    assert candidate["status"] == "blocked"
    assert candidate["merge_authorized"] is False
    assert candidate["reason_codes"] == ["approval-and-applicability-evidence-not-wired"]
    assert candidate["canonical_applicability_evaluated"] is False

    dispatch = evaluate_merge_dispatch_applicability(
        transport, repository=_tdispatch.REPO, github_client=client,
        evaluated_at=_tdispatch.NOW,
    )
    assert dispatch["status"] == "applicable"
    assert dispatch["merge_authorized"] is True
    assert dispatch["dispatch_checks_passed"] is True
    assert dispatch["reason_codes"] == []
    assert dispatch["canonical_applicability_evaluated"] is True
    canonical = dispatch["canonical_applicability_result"]
    assert canonical is not None
    assert canonical["status"] == "applicable"
    assert canonical["merge_authorized"] is True
    assert canonical["changed_bindings"] == []
    assert canonical["reason_codes"] == []
    # The dispatch receipt carries the candidate receipt it started from,
    # bound to the same authorization and the same exact head.
    assert dispatch["admission_receipt"]["authorization_id"] == candidate["authorization_id"]
    assert dispatch["authorization_id"] == candidate["authorization_id"]
    assert dispatch["expected_head_sha"] == candidate["expected_head_sha"]
    assert dispatch["observed_head_sha"] == _tdispatch.HEAD


def test_production_sequence_blocked_candidate_blocks_dispatch_without_canonical():
    client, transport = _client_and_transport(merge_admission_method_or_none="merge")
    candidate = actions.evaluate_merge_admission_transport(
        transport, repository=_tdispatch.REPO, github_client=client,
        evaluated_at=_tdispatch.NOW,
    )
    assert candidate["merge_authorized"] is False
    dispatch = evaluate_merge_dispatch_applicability(
        transport, repository=_tdispatch.REPO, github_client=client,
        evaluated_at=_tdispatch.NOW,
    )
    assert dispatch["status"] == "blocked"
    assert dispatch["merge_authorized"] is False
    assert dispatch["dispatch_checks_passed"] is False
    assert dispatch["canonical_applicability_evaluated"] is False
    assert dispatch["canonical_applicability_result"] is None
    assert "merge-dispatch-blocked-by-admission" in dispatch["reason_codes"]
