from dataclasses import replace

import pytest

from scripts.agent_os_pr_remediation.models import (
    EvidenceValidationError,
    canonical_json,
    deterministic_id,
)
from scripts.agent_os_pr_remediation.normalization import normalize_pr_snapshot


def _snapshot():
    return {
        "repository": "Blummer92/agent-os",
        "pr_number": 5,
        "base_branch": "main",
        "head_branch": "agent/five",
        "head_sha": "a" * 40,
        "state": "open",
        "merged": False,
        "draft": True,
        "changed_files": ["b.py", "a.py"],
    }


def test_canonical_json_and_identity_are_deterministic():
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert deterministic_id({"a": 1, "b": 2}) == deterministic_id({"b": 2, "a": 1})


def test_custom_objects_are_rejected():
    class Custom:
        pass

    with pytest.raises(EvidenceValidationError):
        canonical_json(Custom())


def test_bool_does_not_satisfy_integer_field():
    payload = _snapshot()
    payload["pr_number"] = True
    with pytest.raises(EvidenceValidationError):
        normalize_pr_snapshot(payload)


def test_authority_fields_cannot_become_true():
    payload = _snapshot()
    payload["execution_authorized"] = True
    with pytest.raises(EvidenceValidationError):
        normalize_pr_snapshot(payload)


def test_snapshot_identity_changes_with_evidence():
    first = normalize_pr_snapshot(_snapshot())
    second = replace(first, draft=False)
    assert first.evidence_id != second.evidence_id
