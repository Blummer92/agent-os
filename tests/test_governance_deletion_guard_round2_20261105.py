"""Negative controls for the 2026-11-05 governance round-2 deletion.

Retired 2026-11-05 (base main 7f293b59), 8 modules, 2246 prod lines:
- scripts/agent_os_pr_remediation/high_reasoning_proposal.py (618)
- scripts/agent_os_pr_remediation/time_to_find_bugs_benchmark.py (349)
- src/instructional_workflow_contracts/ppux_experiment_evidence.py (159)
- src/instructional_workflow_contracts/assessment_experiment_evidence.py (85)
- src/instructional_workflow_contracts/classroom_workspace_provisioner.py (279)
- src/instructional_workflow_contracts/classroom_unit_workspace_resolver.py (222)
- src/instructional_workflow_contracts/classroom_workspace_drive_adapter.py (212)
- src/instructional_workflow_contracts/classroom_artifact_candidate_verification.py (322)

All had zero production importers; only their own test files referenced
them (the #3024 test file went with its only implementation). The shared
experiment-evidence core, the #846 assessment standard and fixtures, the
classroom_unit_workspace module, and the review-evidence packet builder all
stay. These controls pin the deletion and prove the neighbours survived.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

DELETED_PATHS = [
    "scripts/agent_os_pr_remediation/high_reasoning_proposal.py",
    "scripts/agent_os_pr_remediation/time_to_find_bugs_benchmark.py",
    "scripts/agent_os_pr_remediation/high-reasoning-proposal-contract.md",
    "scripts/agent_os_pr_remediation/TTFD_BENCHMARK.md",
    "tests/agent_os_pr_remediation/test_high_reasoning_proposal.py",
    "tests/agent_os_pr_remediation/test_time_to_find_bugs_benchmark.py",
    "src/instructional_workflow_contracts/ppux_experiment_evidence.py",
    "src/instructional_workflow_contracts/assessment_experiment_evidence.py",
    "src/instructional_workflow_contracts/classroom_workspace_provisioner.py",
    "src/instructional_workflow_contracts/classroom_workspace_provisioner.md",
    "src/instructional_workflow_contracts/classroom_unit_workspace_resolver.py",
    "src/instructional_workflow_contracts/classroom_unit_workspace_resolver.md",
    "src/instructional_workflow_contracts/classroom_workspace_drive_adapter.py",
    "src/instructional_workflow_contracts/classroom_workspace_drive_adapter.md",
    "src/instructional_workflow_contracts/classroom_artifact_candidate_verification.py",
    "tests/test_ppux_experiment_evidence.py",
    "tests/test_assessment_experiment_evidence.py",
    "tests/test_classroom_workspace_provisioner.py",
    "tests/test_classroom_unit_workspace_resolver.py",
    "tests/test_classroom_workspace_drive_adapter.py",
    "tests/test_issue_3024_legacy_drive_artifact_identity.py",
]

DELETED_IMPORTS = [
    # (dotted name, repo directory that is the parent package's __path__)
    # NOTE: plain importlib.util.find_spec() is the WRONG check here. An
    # editable install maps instructional_workflow_contracts.* to a stale
    # lane checkout, so find_spec() returns that copy even when the repo
    # file is gone. PathFinder with the repo's own parent path tests the
    # repo tree itself; normal imports already resolve from the repo.
    (
        "scripts.agent_os_pr_remediation.high_reasoning_proposal",
        "scripts/agent_os_pr_remediation",
    ),
    (
        "scripts.agent_os_pr_remediation.time_to_find_bugs_benchmark",
        "scripts/agent_os_pr_remediation",
    ),
    (
        "instructional_workflow_contracts.ppux_experiment_evidence",
        "src/instructional_workflow_contracts",
    ),
    (
        "instructional_workflow_contracts.assessment_experiment_evidence",
        "src/instructional_workflow_contracts",
    ),
    (
        "instructional_workflow_contracts.classroom_workspace_provisioner",
        "src/instructional_workflow_contracts",
    ),
    (
        "instructional_workflow_contracts.classroom_unit_workspace_resolver",
        "src/instructional_workflow_contracts",
    ),
    (
        "instructional_workflow_contracts.classroom_workspace_drive_adapter",
        "src/instructional_workflow_contracts",
    ),
    (
        "instructional_workflow_contracts.classroom_artifact_candidate_verification",
        "src/instructional_workflow_contracts",
    ),
]


@pytest.mark.parametrize("rel", DELETED_PATHS)
def test_retired_path_is_absent(rel: str) -> None:
    assert not (REPO_ROOT / rel).exists(), f"retired path still present: {rel}"


@pytest.mark.parametrize("name,parent_dir", DELETED_IMPORTS)
def test_retired_module_is_not_importable(name: str, parent_dir: str) -> None:
    from importlib.machinery import PathFinder

    spec = PathFinder.find_spec(name, [str(REPO_ROOT / parent_dir)])
    assert spec is None, f"retired module still importable from repo: {name}"


def test_neighbouring_canonical_modules_still_import() -> None:
    from instructional_workflow_contracts import (
        validate_classroom_unit_workspace,
        validate_experiment_evidence,
    )
    from scripts.agent_os_pr_remediation.review_evidence import (
        build_review_evidence_packet,
    )

    assert validate_experiment_evidence is not None
    assert validate_classroom_unit_workspace is not None
    assert build_review_evidence_packet is not None
