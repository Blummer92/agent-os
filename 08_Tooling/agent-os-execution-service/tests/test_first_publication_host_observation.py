from __future__ import annotations

import inspect

import pytest

from agent_os_execution_service import first_publication_host_observation as observation


def test_only_caller_identity_is_one_content_addressed_source_capsule() -> None:
    fields = observation.FirstPublicationActivationIdentity.__dataclass_fields__
    assert tuple(fields) == ("source_capsule_id",)
    value = observation.FirstPublicationActivationIdentity(
        source_capsule_id="pre-publication-evidence:" + "1" * 64
    )
    assert value.source_capsule_id.startswith("pre-publication-evidence:")
    for malformed in (
        "latest",
        "pre-publication-evidence:abc",
        "executor-handoff:" + "1" * 64,
    ):
        with pytest.raises(ValueError):
            observation.FirstPublicationActivationIdentity(source_capsule_id=malformed)


def test_acceptance_criteria_are_bounded_to_exact_canonical_section() -> None:
    body = """# Contract

## Acceptance criteria
- [ ] first exact criterion
- second exact criterion

## Authorization
not acceptance
"""
    assert observation._acceptance_criteria(body) == (
        "first exact criterion",
        "second exact criterion",
    )
    with pytest.raises(observation.FirstPublicationHostObservationError):
        observation._acceptance_criteria("# No acceptance section")


def test_host_command_surface_is_fixed_git_observation_only() -> None:
    source = inspect.getsource(observation._subprocess_command)
    assert 'argv[0] != "git"' in source
    for forbidden in ("shell=True", "bash", "sh -c", "credential", "token"):
        assert forbidden not in source


def test_composition_reuses_existing_owners_and_delegates_once() -> None:
    source = inspect.getsource(observation.activate_first_publication_from_host)
    assert source.count("load_source_pre_publication_evidence(") == 1
    assert source.count("reacquire_execution_authorization(") == 1
    assert source.count("verify_exact_lineage(") == 1
    assert source.count("acquire_issue_operational_state(") == 1
    assert source.count("build_live_route_context(") == 1
    assert source.count("project_pre_pr_runtime_capabilities(") == 1
    assert source.count("select_executor_route(") == 1
    assert source.count("activate_first_publication_source(") == 1


def test_composition_has_no_publication_scheduler_lease_or_retry_surface() -> None:
    source = inspect.getsource(observation)
    for forbidden in (
        "publish_production_handoff",
        "publish_authorized_validation_handoff",
        "workflow_scheduler.scheduler",
        "acquire_lease",
        "automatic_retry",
        "provider_fallback",
        "append_checkpoint(",
        "append_resume_plan(",
        "append_route_decision(",
    ):
        assert forbidden not in source


def test_governance_path_set_is_fixed_not_caller_selected() -> None:
    assert observation._GOVERNANCE_PATHS == (
        "AGENTS.md",
        "00_Governance/ownership-and-source-of-truth.md",
        "00_Governance/write-authorization-policy.md",
        "04_Registry/agent-inheritance-registry.md",
        "04_Registry/responsibility-matrix.md",
        "02_Agent_Overlays/github-service-agent.md",
        "01_Shared_Standards/github/safe-implementation-lane.md",
        "01_Shared_Standards/global-engineering/testing-and-release.md",
        "01_Shared_Standards/python/INDEX.md",
    )
