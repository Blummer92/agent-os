"""Executable regressions for the release adapter, independent of core internals."""
import copy
import json
import os
import subprocess
import sys
import typing
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pytest

from test_2149_release_lifecycle_admission import (
    HEAD, _terminal, closure_packet, evidence, release_run as wrapper,
)
from scripts import agent_os_release_run_core as core

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "agent-os-release-run.py"
PUBLIC = {
    "SCHEMA_NAME", "SCHEMA_VERSION", "CLASSIFICATIONS", "SUCCESS_CHECKS",
    "MERGE_METHODS", "BRANCH_STATES", "PR_LIFECYCLE_STATES",
    "REQUIRED_REFRESH_INVALIDATIONS", "ReleaseRunState", "EvidenceState",
    "RequirementResult", "ValidationFailureClassification", "ValidationFailureEvidence",
    "classify_validation_failure", "AdmissionStatus", "LifecycleMutationAuthorization",
    "LifecycleStateSnapshot", "evaluate_lifecycle_mutation", "evaluate_release_run", "main",
}


def run_cli(*argv):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-B", "-m", "scripts.agent-os-release-run", *map(str, argv)], cwd=ROOT,
        text=True, capture_output=True, check=False, env=env,
    )


def test_adm01_import_preserves_sys_path_even_wrapper_first():
    code = (
        "import importlib.util,sys;"
        "before=list(sys.path);"
        f"spec=importlib.util.spec_from_file_location('standalone', {str(WRAPPER)!r});"
        "mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);"
        "assert sys.path==before, (before,sys.path)"
    )
    p = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                       text=True, capture_output=True, check=False)
    assert p.returncode == 0, p.stderr


def test_adm02_explicit_intended_release_surface():
    assert set(wrapper.__all__) == PUBLIC
    assert {name for name in dir(wrapper) if not name.startswith("_")} == PUBLIC
    assert wrapper.ReleaseRunState is core.ReleaseRunState


def test_adm03_private_helpers_are_not_passed_through():
    assert not hasattr(wrapper, "_source_identifier_strings")
    assert core._source_identifier_strings(["run:7"]) == ("run:7",)


@dataclass
class Leaf:
    value: int


@dataclass
class Envelope:
    maybe: typing.Optional[tuple[Leaf, ...]]
    either: str | tuple[int, ...]
    matrix: list[tuple[int, str]]
    payload: dict[str, list[int]]
    derived: int = field(init=False, default=3)


def raw_record():
    return json.loads('{"maybe":[{"value":4}],"either":[8],"matrix":[[1,"x"]],"payload":{"a":[2]}}')


def test_adm04_missing_required_field_is_named():
    raw = raw_record()
    del raw["maybe"]
    with pytest.raises(ValueError, match=r"envelope[.]maybe is required"):
        wrapper._construct_exact(Envelope, raw, "envelope")


def test_adm05_init_false_field_is_rejected_as_input():
    with pytest.raises(ValueError, match="unsupported input"):
        wrapper._construct_exact(Envelope, {**raw_record(), "derived": 3}, "envelope")


def test_adm06_recursive_json_tuple_and_dataclass_roundtrip():
    rec = wrapper._construct_exact(Envelope, raw_record(), "envelope")
    assert rec.maybe == (Leaf(4),) and type(rec.maybe[0]) is Leaf
    assert rec.either == (8,)
    assert rec.matrix == [(1, "x")]
    assert wrapper._construct_exact(Envelope, {**raw_record(), "maybe": None}, "envelope").maybe is None


def test_adm07_nested_inputs_are_detached_and_typed():
    raw = raw_record()
    rec = wrapper._construct_exact(Envelope, raw, "envelope")
    rec.payload["a"].append(7)
    assert raw["payload"]["a"] == [2]
    raw["payload"]["a"] = [True]
    with pytest.raises(TypeError, match=r"envelope[.]payload"):
        wrapper._construct_exact(Envelope, raw, "envelope")


def test_adm08_hint_resolution_cached_and_failure_is_validation_error(monkeypatch):
    hits = []
    real = typing.get_type_hints
    wrapper._hints.cache_clear()
    monkeypatch.setattr(typing, "get_type_hints", lambda cls: (hits.append(cls), real(cls))[1])
    wrapper._construct_exact(Envelope, raw_record(), "envelope")
    wrapper._construct_exact(Envelope, raw_record(), "envelope")
    assert hits == [Envelope, Leaf]

    @dataclass
    class Broken:
        item: "UnavailableType"

    with pytest.raises(ValueError, match="annotation"):
        wrapper._construct_exact(Broken, {"item": 1}, "broken")
    wrapper._hints.cache_clear()


@pytest.mark.parametrize("name,packet_field", [
    ("repository", "repository"), ("issue_number", "issue_number"),
    ("pull_request_number", "pull_request_number"), ("observed_head_sha", "source_head"),
    ("issue_state", "issue_state"),
])
def test_adm09_missing_identity_cannot_match_itself(name, packet_field):
    packet = closure_packet()
    packet["snapshot"][packet_field] = None
    state = wrapper.evaluate_release_run(evidence(**{name: None, "issue_closure_lifecycle": packet}))
    assert state.issue_closure_authorized is False
    assert state.classification == "BLOCKED" and state.blockers == [f"invalid-release-identity:{name}"]


def test_adm10_top_level_normalization_preserves_content_bound_record():
    packet = closure_packet()
    state = wrapper.evaluate_release_run(evidence(
        repository=" HTTPS://github.com/Blummer92/agent-os/ ",
        observed_head_sha=f" {HEAD.upper()} ", issue_state=" OPEN ",
        issue_closure_lifecycle=packet,
    ))
    assert state.issue_closure_authorized is True
    assert state.observed_head_sha == HEAD
    assert state.next_action == "post-completion-comment-before-closure"


@pytest.mark.parametrize("field,bad,reason", [
    ("repository", "other-owner/agent-os", "identity-repository-mismatch"),
    ("issue_number", 1111, "identity-issue-mismatch"),
    ("expected_base_head", "c" * 40, "pull-request-base-changed"),
    ("expected_merged", False, "pull-request-merged-state-changed"),
    ("expected_review_state", "blocked", "review-state-changed"),
    ("expected_unresolved_threads", 2, "review-thread-state-changed"),
    ("expected_lifecycle_labels", ("status:other",), "lifecycle-label-state-changed"),
    ("observed_at_revision", "previous-readback", "authorization-stale"),
])
def test_adm11_independent_foreign_or_stale_authorization_refused(field, bad, reason):
    original = closure_packet()
    changes = dict(original["authorization"], authorization_id="", authorization_revision="")
    changes["authorized_mutations"] = tuple(changes["authorized_mutations"])
    changes["expected_lifecycle_labels"] = tuple(changes["expected_lifecycle_labels"])
    changes[field] = bad
    # Both records are internally canonical; they are not a matching pair.
    from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import LifecycleMutationAuthorization

    original["authorization"] = LifecycleMutationAuthorization(**changes).to_dict()
    state = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=original))
    assert state.issue_closure_authorized is False
    assert f"closure-not-admitted:{reason}" in state.blockers


@pytest.mark.parametrize("field,bad", [
    ("base_head", "c" * 40), ("review_state", "blocked"),
    ("unresolved_threads", 2), ("lifecycle_labels", ["status:other"]),
    ("observed_revision", "previous-readback"), ("pr_state", "open"),
])
def test_adm11_independent_release_snapshot_facts_are_bound(field, bad):
    out = wrapper.evaluate_release_run(evidence(
        issue_closure_lifecycle=closure_packet(), **{field: bad}))
    assert out.issue_closure_authorized is False and out.classification == "BLOCKED"
    assert out.blockers[-1] == "closure-binding-mismatch:" + ("merged" if field == "pr_state" else field)


@pytest.mark.parametrize("packet", [
    [], "bad", {}, {"authorization": {}},
    {"authorization": None, "snapshot": None},
    {"authorization": 4, "snapshot": {}},
    {"authorization": {}, "snapshot": {}},
])
def test_adm12_malformed_lifecycle_is_structurally_blocked(packet):
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=packet, issue_closure_authorized=True))
    assert out.issue_closure_authorized is False and out.classification == "BLOCKED"
    assert any(code.startswith("invalid-closure-evidence:") for code in out.blockers)


def test_adm13_unknown_nested_fields_fail_closed_without_reflecting_values():
    packet = closure_packet()
    packet["authorized"] = "private-field-value"
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=packet, issue_closure_authorized=True))
    assert out.issue_closure_authorized is False
    assert out.blockers == ["invalid-closure-evidence:packet-shape"]


def test_adm14_bound_mismatch_reports_field_without_echoing_value():
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=closure_packet(issue_number=1931)))
    assert not out.issue_closure_authorized
    assert out.blockers == ["closure-binding-mismatch:issue_number"]


def test_adm15_core_mutation_cannot_change_callers_nested_evidence(monkeypatch):
    incoming = evidence(issue_closure_lifecycle=closure_packet())
    original = copy.deepcopy(incoming)
    module = wrapper._core() if hasattr(wrapper, "_core") else wrapper
    hook = "evaluate_release_run" if module is not wrapper else "_evaluate_release_run_core"
    evaluator = getattr(module, hook)

    def touching_core(data):
        data["issue_closure_lifecycle"]["authorization"]["expected_lifecycle_labels"].append("changed")
        data["required_checks"]["new"] = "success"
        return evaluator(data)

    monkeypatch.setattr(module, hook, touching_core)
    assert wrapper.evaluate_release_run(incoming).issue_closure_authorized
    assert incoming == original


@pytest.mark.parametrize("shape", [{}, {"issue_number": True}, {"pull_request_number": "2"}, {"observed_head_sha": "zzz"}])
def test_adm16_missing_or_invalid_top_level_identity_refused(shape):
    value = evidence(**shape) if shape else {}
    out = wrapper.evaluate_release_run(value)
    assert out.classification == "BLOCKED" and not out.issue_closure_authorized
    assert any(code.startswith("invalid-release-identity:") for code in out.blockers)


def test_unbound_content_must_not_be_minted_by_wrapper():
    packet = closure_packet()
    del packet["authorization"]["authorization_id"]
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=packet))
    assert not out.issue_closure_authorized
    assert out.blockers == ["invalid-closure-evidence:missing-content-binding"]


def test_adm17_cli_status_and_shape_from_clean_working_directory(tmp_path):
    receipts = ["merge", "completion-comment", "lineage-terminalized", "close-issue", "final-report"]
    complete = _terminal()
    complete["side_effects_performed"] = receipts
    for expected, item in ((0, complete), (1, evidence()), (1, evidence(issue_closure_lifecycle=[]))):
        file = tmp_path / f"case-{expected}.json"
        file.write_text(json.dumps(item))
        p = run_cli(file)
        assert p.returncode == expected, p.stdout + p.stderr
        result = json.loads(p.stdout)
        assert set(result) == {item.name for item in fields(core.ReleaseRunState)}
        assert result["classification"] == ("COMPLETED" if expected == 0 else "BLOCKED")


def test_adm18_cli_serializes_enum_and_datetime(tmp_path, monkeypatch, capsys):
    class Phase(Enum):
        COMPLETE = "done"
    stamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
    state = core.ReleaseRunState(classification="COMPLETED", phase=Phase.COMPLETE,
                                 checkpoint_phase=stamp)
    monkeypatch.setattr(wrapper, "evaluate_release_run", lambda data: state)
    p = tmp_path / "input.json"
    p.write_text("{}")
    monkeypatch.setattr(sys, "argv", [str(WRAPPER), str(p)])
    assert wrapper.main() == 0
    got = json.loads(capsys.readouterr().out)
    assert got["phase"] == "done"
    assert got["checkpoint_phase"] == stamp.isoformat()


@pytest.mark.parametrize("kind,reason", [
    ("missing", "FileNotFoundError"), ("malformed", "JSONDecodeError"),
    ("directory", "IsADirectoryError"), ("encoding", "UnicodeDecodeError"),
])
def test_adm19_cli_file_failure_json_not_traceback(tmp_path, kind, reason):
    file = tmp_path / "test.json"
    if kind == "malformed":
        file.write_text("{broken")
    elif kind == "directory":
        file.mkdir()
    elif kind == "encoding":
        file.write_bytes(b"\xff")
    p = run_cli(file)
    assert p.returncode == 2
    assert not p.stderr
    result = json.loads(p.stdout)
    assert set(result) == {item.name for item in fields(core.ReleaseRunState)}
    assert result["classification"] == "BLOCKED"
    assert result["blockers"] == [f"evidence-file:{file}:{reason}"]


def test_adm19_permission_error_uses_the_same_cli_contract(monkeypatch, capsys):
    def denied(*args, **kwargs):
        raise PermissionError("not for the CLI to echo")
    monkeypatch.setattr(wrapper, "open", denied, raising=False)
    monkeypatch.setattr(sys, "argv", ["script", "denied.json"])
    assert wrapper.main() == 2
    assert json.loads(capsys.readouterr().out)["blockers"] == ["evidence-file:denied.json:PermissionError"]


def test_malformed_packet_never_suggests_side_effect_on_closed_issue():
    out = wrapper.evaluate_release_run(evidence(issue_state="closed", issue_closure_lifecycle=[]))
    assert out.classification == "BLOCKED"
    assert not out.issue_closure_authorized
    assert out.next_action == "stop"
    assert out.blockers == ["invalid-closure-evidence:packet-shape"]


def test_malformed_packet_stays_structured_when_other_fields_are_malformed():
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=[], required_checks=[]))
    assert out.classification == "BLOCKED" and out.next_action == "stop"
    assert out.blockers == ["invalid-closure-evidence:packet-shape"]


@pytest.mark.parametrize("first", ["wrapper", "core"])
def test_import_orders_reuse_the_same_core_type(first):
    code = f"""
import importlib.util, sys
from pathlib import Path
if {first!r} == 'core':
    from scripts import agent_os_release_run_core
before = list(sys.path)
spec = importlib.util.spec_from_file_location('order_probe', {str(WRAPPER)!r})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert before == sys.path
from scripts import agent_os_release_run_core as core
assert mod.ReleaseRunState is core.ReleaseRunState
assert 'agent_os_release_run_core' not in sys.modules
assert mod.evaluate_release_run({{}}).classification == 'BLOCKED'
"""
    p = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                       text=True, capture_output=True, check=False)
    assert p.returncode == 0, p.stderr


def test_unproven_lease_cannot_complete_even_after_closure():
    item = _terminal()
    item["side_effects_performed"].append("final-report")
    item["lease_release_required"] = True
    assert wrapper.evaluate_release_run(item).classification == "BLOCKED"
    assert wrapper.evaluate_release_run(item).next_action == "release-exactly-owned-lease"


def test_direct_script_with_repository_on_import_path_keeps_cli(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence(issue_closure_lifecycle=closure_packet())))
    p = subprocess.run([sys.executable, "-B", str(WRAPPER), str(path)], cwd="/",
                       text=True, capture_output=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert p.returncode == 1, p.stderr
    out = json.loads(p.stdout)
    assert out["issue_closure_authorized"] is True
    assert out["next_action"] == "post-completion-comment-before-closure"


@pytest.mark.parametrize("field", ["authorization_id", "authorization_revision", "snapshot_id"])
def test_content_bound_records_are_never_silently_minted(field):
    packet = closure_packet()
    group = "snapshot" if field == "snapshot_id" else "authorization"
    del packet[group][field]
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=packet))
    assert out.blockers == ["invalid-closure-evidence:missing-content-binding"]
    assert not out.issue_closure_authorized


def test_mutation_of_bound_record_is_refused_before_normalization():
    packet = closure_packet()
    packet["snapshot"]["source_head"] = HEAD.upper()
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=packet))
    assert out.blockers == ["invalid-closure-evidence:record-shape-or-digest"]
    assert not out.issue_closure_authorized


def test_none_is_not_authority_and_does_not_replace_canonical_result():
    state = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=None, issue_closure_authorized=True))
    assert not state.issue_closure_authorized
    assert state.next_action == "request-issue-closure-authorization"


def test_cyclic_programmatic_evidence_stays_blocked():
    cyclic = {}
    cyclic["cycle"] = cyclic
    out = wrapper.evaluate_release_run(evidence(issue_closure_lifecycle=cyclic))
    assert not out.issue_closure_authorized
    assert out.blockers == ["invalid-release-evidence:non-native-or-unbounded"]
