from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_os_execution_service.candidate_environment_provenance import (
    append_candidate_environment_provenance,
    build_candidate_environment_provenance,
    derive_initial_required_environment_spec,
    load_candidate_environment_provenance,
)
from scripts.agent_os_execution_capabilities.dependencies import DependencyEcosystem


def _project(path: Path, name: str) -> None:
    target = path / name
    target.mkdir(parents=True)
    (target / "pyproject.toml").write_text(f"[project]\nname='{name.replace('/', '-')}'\nversion='0.1.0'\n", encoding="utf-8")


def _python_repo(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    for name in (
        "src",
        "08_Tooling/agent-memory-context-manager",
        "08_Tooling/reusable-capability-registry",
        "08_Tooling/workflow-scheduler",
        "08_Tooling/visual-asset-intake",
    ):
        _project(root, name)
    (root / "requirements-dev.txt").write_text(
        "pytest>=7\n"
        "-e ./src\n"
        "-e ./08_Tooling/agent-memory-context-manager\n"
        "-e ./08_Tooling/reusable-capability-registry[test]\n"
        "-e ./08_Tooling/workflow-scheduler\n"
        "-e ./08_Tooling/visual-asset-intake\n",
        encoding="utf-8",
    )
    return root


def test_python_spec_is_content_addressed_and_structural(tmp_path: Path) -> None:
    root = _python_repo(tmp_path)
    tests = ("workflow-scheduler-gce-gcloud-adapter",)
    first = derive_initial_required_environment_spec(root, required_tests=tests)
    second = derive_initial_required_environment_spec(root, required_tests=tests)
    assert first == second
    assert first.ecosystem is DependencyEcosystem.PYTHON_PIP
    assert first.package_root == "."
    assert first.runtime_requirement == ">=3.11"
    assert first.approved_source_identity == "pypi.org/simple"
    assert first.required_validation_command_ids == tests
    assert len(first.local_project_requirements) == 5
    assert all(item.editable for item in first.local_project_requirements)


def test_manifest_or_local_project_drift_changes_environment_identity(tmp_path: Path) -> None:
    root = _python_repo(tmp_path)
    tests = ("workflow-scheduler-gce-gcloud-adapter",)
    before = derive_initial_required_environment_spec(root, required_tests=tests)
    (root / "requirements-dev.txt").write_text((root / "requirements-dev.txt").read_text() + "pyyaml>=6\n", encoding="utf-8")
    after_manifest = derive_initial_required_environment_spec(root, required_tests=tests)
    assert after_manifest.required_environment_id != before.required_environment_id
    (root / "src" / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
    after_source = derive_initial_required_environment_spec(root, required_tests=tests)
    assert after_source.required_environment_id != after_manifest.required_environment_id


def test_undeclared_python_local_source_fails_closed(tmp_path: Path) -> None:
    root = _python_repo(tmp_path)
    (root / "requirements-dev.txt").write_text((root / "requirements-dev.txt").read_text() + "-e ./other\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not represented"):
        derive_initial_required_environment_spec(root, required_tests=("workflow-scheduler-gce-gcloud-adapter",))


def test_environment_provenance_round_trip_reuses_existing_namespace(tmp_path: Path) -> None:
    root = _python_repo(tmp_path)
    value = build_candidate_environment_provenance(
        candidate_provenance_id="pre-publication-evidence:" + "a" * 64,
        candidate_sha="b" * 40,
        repository_root=root,
        required_tests=("workflow-scheduler-gce-gcloud-adapter",),
    )
    evidence_id = append_candidate_environment_provenance(tmp_path / "store", value)
    loaded = load_candidate_environment_provenance(tmp_path / "store", evidence_id)
    assert loaded == value
    assert loaded.execution_authorized is False
    assert loaded.runtime_ready is False
    assert loaded.side_effects_performed is False
    assert (tmp_path / "store" / "pre-publication-producer-evidence").is_dir()


def test_required_tests_change_environment_identity(tmp_path: Path) -> None:
    root = _python_repo(tmp_path)
    one = derive_initial_required_environment_spec(root, required_tests=("a",))
    two = derive_initial_required_environment_spec(root, required_tests=("b",))
    assert one.required_environment_id != two.required_environment_id
