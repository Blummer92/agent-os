from __future__ import annotations

import ast
import inspect

import pytest

import agent_os_execution_service.production_handoff_publication as publication
from agent_os_execution_service.production_handoff_publication import (
    ProductionHandoffPublicationIdentity,
)


def test_bounded_identity_contract_rejects_noncanonical_values() -> None:
    valid = {
        "capsule_id": "pre-publication-evidence:" + "a" * 64,
        "route_decision_id": "executor-route-decision:" + "b" * 64,
        "dependency_readiness_id": "dependency-readiness:" + "c" * 64,
    }
    assert ProductionHandoffPublicationIdentity(**valid).capsule_id == valid["capsule_id"]
    for name in tuple(valid):
        broken = dict(valid)
        broken[name] = "bad"
        with pytest.raises(ValueError):
            ProductionHandoffPublicationIdentity(**broken)


def test_entrypoint_argv_is_identity_only() -> None:
    parser = publication._parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    assert option_strings == {
        "--capsule-id",
        "--route-decision-id",
        "--dependency-readiness-id",
        "--help",
    }
    source = inspect.getsource(publication)
    for forbidden in (
        "--store-root",
        "--repository-root",
        "--workspace-parent",
        "--lease-directory",
        "--python-path",
        "--command",
        "--credential",
    ):
        assert forbidden not in source


def test_fixed_handoff_profile_is_bounded_and_not_caller_selectable() -> None:
    assert publication.REQUIRED_RETURN_EVIDENCE == ("exact-head-sha", "test-results")
    assert publication.STOP_CONDITIONS == (
        "excluded-surface-entered",
        "scope-expanded",
    )


def test_activation_calls_1409_not_1243_directly() -> None:
    tree = ast.parse(inspect.getsource(publication))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "publish_authorized_validation_handoff" in imported
    assert "publish_authorized_validation_handoff" in calls
    assert "publish_governed_handoff" not in imported
    assert "publish_governed_handoff" not in calls


def test_no_scheduler_lease_or_second_persistence_owner_surface() -> None:
    source = inspect.getsource(publication)
    assert "workflow_scheduler.scheduler" not in source
    assert "acquire_lease" not in source
    assert "append_pre_publication_evidence" not in source
    assert "append_executor_handoff" not in source
    assert "persist_current_invocation_descriptor" not in source


def test_capsule_remains_non_authorizing() -> None:
    capsule_source = inspect.getsource(publication.load_pre_publication_evidence.__module__)
    # The activation does not mutate or replace capsule authority. Its own source
    # must never assign any capsule authority field true.
    source = inspect.getsource(publication)
    assert "publication_authorized=True" not in source
    assert "execution_authorized=True" not in source
    assert "merge_authorized=True" not in source
    assert "external_writes_authorized=True" not in source
    assert capsule_source
