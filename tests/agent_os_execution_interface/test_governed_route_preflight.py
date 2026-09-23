"""Adversarial coverage for the #1237 execution-interface governed-route seam."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
)
from scripts.agent_os_execution_interface.governed_route_preflight import (
    GOVERNED_CHECKOUT_MARKERS,
    GovernedRoutePreflightReason,
    GovernedRoutePreflightStatus,
    resolve_governed_route_preflight,
    serialize_preflight_result,
)
from scripts.agent_os_execution_interface import hook_adapter

REPOSITORY = "Blummer92/agent-os"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_digest(label)}"


def _descriptor(label: str = "one", **overrides: object) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": REPOSITORY,
        "issue_number": 1259,
        "issue_or_handoff_identity": "issue:1259",
        "handoff_id": _id("executor-handoff", f"handoff-{label}"),
        "route_decision_id": _id("executor-route-decision", f"route-{label}"),
        "execution_service_request_fingerprint": _id("execution-request", f"request-{label}"),
        "authorization_id": _id("authorization", f"authorization-{label}"),
        "source_ref": "refs/heads/agent/1259-governed-route",
        "source_sha": "a" * 40,
        "checkpoint_id": _id("agent-os.execution-checkpoint", f"checkpoint-{label}"),
        "resume_plan_id": _id("agent-os.execution-checkpoint.resume-plan", f"resume-{label}"),
        "environment_profile_id": _id("environment-profile", f"profile-{label}"),
        "environment_health_evidence_id": _id("environment-health", f"health-{label}"),
        "required_environment_id": _id("required-environment", f"required-{label}"),
        "dependency_readiness_evidence_id": _id("dependency-readiness", f"readiness-{label}"),
        "execution_surface_id": "execution-surface:gce-agent-os-test",
        "workspace_identity": _id("pilot-workspace", f"workspace-{label}"),
        "workflow_runtime_identity": _id("workflow-runtime", f"runtime-{label}"),
        "candidate_packet_id": _id("candidate-packet", f"packet-{label}"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", f"configuration-{label}"),
        "execution_id": f"execution-1259-{label}",
        "invocation_id": f"invocation-1259-{label}",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


@pytest.fixture
def governed_checkout(tmp_path):
    """A minimal checkout carrying every governed marker file."""
    root = tmp_path / "checkout"
    for marker in GOVERNED_CHECKOUT_MARKERS:
        path = root / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")
    return root


@pytest.fixture
def store_root(tmp_path):
    return tmp_path / "store"


def _resolve(governed_checkout, store_root, *, issues=(1259,), repository=REPOSITORY):
    return resolve_governed_route_preflight(
        checkout_root=governed_checkout,
        repository=repository,
        issue_numbers=issues,
        store_root=store_root,
    )


# --- required behavior 3 / 13: exactly one descriptor -> existing ingress -----


def test_single_descriptor_yields_existing_immutable_handoff(governed_checkout, store_root):
    descriptor = _descriptor()
    append_invocation_descriptor(store_root, descriptor)

    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.GOVERNED_RESUME_AVAILABLE
    assert result.handoff_id == descriptor.handoff_id
    assert result.resume_command == f"/agent-os resume {descriptor.handoff_id}"
    assert result.repository == REPOSITORY
    assert result.issue_number == 1259


def test_available_result_grants_no_authority_and_no_side_effects(
    governed_checkout, store_root
):
    append_invocation_descriptor(store_root, _descriptor())

    result = _resolve(governed_checkout, store_root)

    assert result.local_gh_absence_is_execution_blocker is False
    assert result.repository_implementation_authorized is False
    assert result.execution_authorized is False
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.external_writes_authorized is False
    assert result.scheduler_invoked is False
    assert result.handoff_persisted is False
    assert result.side_effects_performed is False


# --- required behavior 19: repeated discovery persists nothing ---------------


def test_repeated_resolution_is_deterministic_and_persists_nothing(
    governed_checkout, store_root
):
    append_invocation_descriptor(store_root, _descriptor())
    before = sorted(path.name for path in (store_root / "invocations").iterdir())

    first = _resolve(governed_checkout, store_root)
    second = _resolve(governed_checkout, store_root)

    assert first == second
    assert first.result_id == second.result_id
    assert sorted(path.name for path in (store_root / "invocations").iterdir()) == before


# --- required behavior 4 / 14: zero descriptors -> bounded not-found ---------


def test_zero_descriptors_returns_bounded_not_found(governed_checkout, store_root):
    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.NOT_FOUND
    assert result.reason_codes == (
        GovernedRoutePreflightReason.DISCOVERY_NO_MATCHING_DESCRIPTOR,
    )
    assert result.handoff_id is None
    assert result.resume_command is None
    notice = " ".join(hook_adapter.render_preflight_notice(result).split()).lower()
    assert "do not synthesize a handoff identity" in notice
    assert "do not silently fall back to local git/gh tooling" in notice


def test_other_issue_descriptor_does_not_match(governed_checkout, store_root):
    append_invocation_descriptor(
        store_root,
        _descriptor(issue_number=1239, issue_or_handoff_identity="issue:1239"),
    )

    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.NOT_FOUND


# --- required behavior 5 / 15: multiple descriptors -> needs-decision --------


def test_multiple_descriptors_return_needs_decision_without_latest_heuristic(
    governed_checkout, store_root
):
    append_invocation_descriptor(store_root, _descriptor("one"))
    append_invocation_descriptor(store_root, _descriptor("two"))

    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.DISCOVERY_MULTIPLE_MATCHING_DESCRIPTORS,
    )
    assert result.handoff_id is None
    assert "'latest'" in hook_adapter.render_preflight_notice(result)


# --- required behavior 6 / 16: corrupt or unavailable store -> fail closed ---


def test_corrupt_descriptor_fails_closed(governed_checkout, store_root):
    append_invocation_descriptor(store_root, _descriptor())
    corrupt = next((store_root / "invocations").iterdir())
    corrupt.write_text("{not json", encoding="utf-8")

    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.DISCOVERY_DESCRIPTOR_INTEGRITY_UNVERIFIED,
    )
    assert result.handoff_id is None


def test_unavailable_store_fails_closed(governed_checkout, store_root, monkeypatch):
    (store_root / "invocations").mkdir(parents=True)

    def _boom(self):
        raise OSError("store unavailable")

    monkeypatch.setattr("pathlib.Path.iterdir", _boom)

    result = _resolve(governed_checkout, store_root)

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.DISCOVERY_STORE_UNAVAILABLE,
    )


def test_unconfigured_store_fails_closed_without_inventing_a_path(governed_checkout):
    result = resolve_governed_route_preflight(
        checkout_root=governed_checkout,
        repository=REPOSITORY,
        issue_numbers=(1259,),
        store_root=None,
    )

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.DESCRIPTOR_STORE_NOT_CONFIGURED,
    )
    assert result.handoff_id is None


# --- required behavior 9: non-Agent-OS work is untouched --------------------


def test_non_governed_checkout_is_not_applicable_and_silent(tmp_path, store_root):
    plain = tmp_path / "other-repo"
    plain.mkdir()
    append_invocation_descriptor(store_root, _descriptor())

    result = resolve_governed_route_preflight(
        checkout_root=plain,
        repository="someone/other-repo",
        issue_numbers=(1259,),
        store_root=store_root,
    )

    assert result.status is GovernedRoutePreflightStatus.NOT_APPLICABLE
    assert result.reason_codes == (GovernedRoutePreflightReason.NOT_AGENT_OS_CHECKOUT,)
    assert hook_adapter.render_preflight_notice(result) == ""


def test_partial_marker_set_is_not_a_governed_checkout(tmp_path, store_root):
    partial = tmp_path / "partial"
    (partial / "AGENTS.md").parent.mkdir(parents=True)
    (partial / "AGENTS.md").write_text("marker\n", encoding="utf-8")

    result = resolve_governed_route_preflight(
        checkout_root=partial,
        repository=REPOSITORY,
        issue_numbers=(1259,),
        store_root=store_root,
    )

    assert result.status is GovernedRoutePreflightStatus.NOT_APPLICABLE


def test_governed_checkout_without_issue_reference_stays_silent(
    governed_checkout, store_root
):
    result = _resolve(governed_checkout, store_root, issues=())

    assert result.status is GovernedRoutePreflightStatus.NOT_APPLICABLE
    assert result.reason_codes == (
        GovernedRoutePreflightReason.NO_GOVERNED_ISSUE_REFERENCE,
    )
    assert hook_adapter.render_preflight_notice(result) == ""


# --- ambiguity is never resolved by heuristic -------------------------------


def test_multiple_issue_references_return_needs_decision(governed_checkout, store_root):
    append_invocation_descriptor(store_root, _descriptor())

    result = _resolve(governed_checkout, store_root, issues=(1259, 1239))

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.AMBIGUOUS_ISSUE_REFERENCE,
    )
    assert result.handoff_id is None


def test_repeated_identical_issue_reference_is_not_ambiguous(
    governed_checkout, store_root
):
    append_invocation_descriptor(store_root, _descriptor())

    result = _resolve(governed_checkout, store_root, issues=(1259, 1259))

    assert result.status is GovernedRoutePreflightStatus.GOVERNED_RESUME_AVAILABLE


def test_unresolved_repository_identity_fails_closed(governed_checkout, store_root):
    result = _resolve(governed_checkout, store_root, repository=None)

    assert result.status is GovernedRoutePreflightStatus.NEEDS_DECISION
    assert result.reason_codes == (
        GovernedRoutePreflightReason.REPOSITORY_IDENTITY_UNRESOLVED,
    )


def test_non_positive_issue_number_is_rejected(governed_checkout, store_root):
    with pytest.raises(TypeError):
        _resolve(governed_checkout, store_root, issues=(0,))


# --- serialization is bounded evidence, not a command channel ---------------


def test_serialized_result_is_bounded_non_authorizing_json(governed_checkout, store_root):
    descriptor = _descriptor()
    append_invocation_descriptor(store_root, descriptor)

    payload = json.loads(serialize_preflight_result(_resolve(governed_checkout, store_root)))

    assert payload["status"] == "governed-resume-available"
    assert payload["handoff_id"] == descriptor.handoff_id
    assert payload["resume_command"] == f"/agent-os resume {descriptor.handoff_id}"
    assert payload["local_gh_absence_is_execution_blocker"] is False
    assert payload["scheduler_invoked"] is False
    assert payload["handoff_persisted"] is False
