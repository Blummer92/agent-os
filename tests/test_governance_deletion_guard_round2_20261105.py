"""Scope guard for the narrowed round-2 governance deletion (PR #3797).

Only two unexported, pure-local PR-remediation utilities are retired. Public
Teacher OS classroom exports, experiment adapters, and the issue #3024 artifact
identity verifier are intentionally retained. This is a repository-local
absence check, not proof that external consumers never existed.
"""

from __future__ import annotations

from importlib.machinery import PathFinder
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

RETIRED_PATHS = (
    "scripts/agent_os_pr_remediation/high_reasoning_proposal.py",
    "scripts/agent_os_pr_remediation/time_to_find_bugs_benchmark.py",
    "scripts/agent_os_pr_remediation/high-reasoning-proposal-contract.md",
    "scripts/agent_os_pr_remediation/TTFD_BENCHMARK.md",
    "tests/agent_os_pr_remediation/test_high_reasoning_proposal.py",
    "tests/agent_os_pr_remediation/test_time_to_find_bugs_benchmark.py",
)

RETAINED_PATHS = (
    "src/instructional_workflow_contracts/classroom_artifact_candidate_verification.py",
    "src/instructional_workflow_contracts/classroom_unit_workspace_resolver.py",
    "src/instructional_workflow_contracts/classroom_workspace_drive_adapter.py",
    "src/instructional_workflow_contracts/classroom_workspace_provisioner.py",
    "src/instructional_workflow_contracts/ppux_experiment_evidence.py",
    "src/instructional_workflow_contracts/assessment_experiment_evidence.py",
    "tests/test_issue_3024_legacy_drive_artifact_identity.py",
    "tests/test_instructional_workflow_contract_integration.py",
)


@pytest.mark.parametrize("relative", RETIRED_PATHS)
def test_only_admitted_round2_paths_are_absent(relative: str) -> None:
    assert not (ROOT / relative).exists(), relative


@pytest.mark.parametrize(
    "module",
    (
        "scripts.agent_os_pr_remediation.high_reasoning_proposal",
        "scripts.agent_os_pr_remediation.time_to_find_bugs_benchmark",
    ),
)
def test_retired_modules_not_importable_from_this_repo(module: str) -> None:
    # Avoid importlib.util.find_spec: editable installs can resolve a stale
    # external worktree instead of testing this repository's actual files.
    package_path = ROOT / "scripts" / "agent_os_pr_remediation"
    assert PathFinder.find_spec(module, [str(package_path)]) is None, module


@pytest.mark.parametrize("relative", RETAINED_PATHS)
def test_classroom_and_experiment_contracts_are_preserved(relative: str) -> None:
    assert (ROOT / relative).is_file(), relative


def test_public_classroom_and_pr_review_exports_remain_usable() -> None:
    from instructional_workflow_contracts import (
        execute_workspace_create,
        plan_classroom_workspace_provisioning,
        resolve_classroom_unit_workspace,
        validate_experiment_evidence,
        verify_classroom_artifact_candidates,
    )
    from scripts.agent_os_pr_remediation import (
        build_review_evidence_packet,
        plan_remediation,
    )

    for value in (
        execute_workspace_create,
        plan_classroom_workspace_provisioning,
        resolve_classroom_unit_workspace,
        validate_experiment_evidence,
        verify_classroom_artifact_candidates,
        build_review_evidence_packet,
        plan_remediation,
    ):
        assert callable(value)
