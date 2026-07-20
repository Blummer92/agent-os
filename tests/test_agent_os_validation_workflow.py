import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"
SCHEDULER_WORKFLOW = ROOT / ".github/workflows/workflow-scheduler-validation.yml"
CLOUD_BUILD = ROOT / "cloudbuild.yaml"

_REQUIREMENTS_INSTALL = re.compile(
    r"python -m pip install -r [\"']?([^\s\"']+)[\"']?"
)
_EDITABLE_INSTALL = re.compile(
    r"python -m pip install -e [\"']\./([^\"'\[]+)"
    r"(?:\[[^\"']+\])?[\"']"
)


def _cache_dependency_paths(content: str) -> set[str]:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("cache-dependency-path:"):
            continue

        value = stripped.split(":", 1)[1].strip()
        if value and value != "|":
            return {value.strip("\"'")}

        parent_indent = len(line) - len(line.lstrip())
        paths: set[str] = set()
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                continue
            indent = len(candidate) - len(candidate.lstrip())
            if indent <= parent_indent:
                break
            paths.add(candidate.strip().strip("\"'"))
        return paths

    return set()


def _installed_dependency_manifests(content: str) -> set[str]:
    manifests = set(_REQUIREMENTS_INSTALL.findall(content))
    for package_path in _EDITABLE_INSTALL.findall(content):
        manifests.add(f"{package_path}/pyproject.toml")
    return manifests


def _assert_dependency_cache_parity(content: str) -> None:
    installed = _installed_dependency_manifests(content)
    cached = _cache_dependency_paths(content)
    missing = sorted(installed - cached)
    stale = sorted(cached - installed)
    assert not missing and not stale, (
        "dependency cache paths must exactly match installed dependency manifests; "
        f"missing={missing}, stale={stale}"
    )


def test_validation_gate_executes_only_canonical_aggregate_command():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert content.count("./scripts/validate-all.sh") == 1
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in content
    assert "Cloud Build validation migration notice" not in content


def test_cloud_build_executes_only_canonical_aggregate_command():
    content = CLOUD_BUILD.read_text(encoding="utf-8")
    assert content.count("./scripts/validate-all.sh") == 1
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in content


def test_validation_gate_preserves_required_workflow_and_job_names():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content


def test_scheduler_validation_preserves_required_workflow_and_job_names():
    content = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    assert "name: Workflow Scheduler Validation" in content
    assert "name: Validate Workflow Scheduler" in content


def test_validation_gate_uses_read_only_permissions_and_bounded_execution():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in content
    assert "contents: write" not in content
    assert "timeout-minutes: 30" in content
    assert "cancel-in-progress: true" in content


def test_validation_gate_installs_same_dependencies_as_cloud_build():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cloudbuild = CLOUD_BUILD.read_text(encoding="utf-8")
    required = [
        "requirements-dev.txt",
        "08_Tooling/workflow-scheduler/requirements.txt",
        "08_Tooling/instructional-materials-coach[test]",
        "08_Tooling/notion-navigation-client[test]",
        "08_Tooling/reusable-capability-registry[test]",
    ]
    for dependency in required:
        assert dependency in workflow
        assert dependency in cloudbuild


def test_validation_gate_cache_paths_match_installed_dependency_manifests():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/setup-python@v5" in content
    assert 'cache: "pip"' in content
    _assert_dependency_cache_parity(content)


def test_scheduler_cache_paths_match_installed_dependency_manifests():
    content = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/setup-python@v5" in content
    assert 'cache: "pip"' in content
    _assert_dependency_cache_parity(content)
    assert _cache_dependency_paths(content) == {
        "08_Tooling/workflow-scheduler/requirements.txt"
    }


def test_parity_check_fails_when_new_install_manifest_is_not_cached():
    incomplete = """
      cache-dependency-path: requirements-dev.txt
      run: |
        python -m pip install -r requirements-dev.txt
        python -m pip install -r added-requirements.txt
    """
    with pytest.raises(AssertionError, match="added-requirements.txt"):
        _assert_dependency_cache_parity(incomplete)


def test_parity_check_fails_when_required_cache_path_is_removed():
    incomplete = """
      cache-dependency-path: |
        requirements-dev.txt
      run: |
        python -m pip install -r requirements-dev.txt
        python -m pip install -e "./08_Tooling/example-package[test]"
    """
    with pytest.raises(AssertionError, match="example-package/pyproject.toml"):
        _assert_dependency_cache_parity(incomplete)


def test_cache_configuration_does_not_replace_install_or_validation_commands():
    aggregate = WORKFLOW.read_text(encoding="utf-8")
    scheduler = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements-dev.txt" in aggregate
    assert "./scripts/validate-all.sh" in aggregate
    assert (
        "python -m pip install -r 08_Tooling/workflow-scheduler/requirements.txt"
        in scheduler
    )
    scheduler_test_command = (
        "PYTHONPATH=src python3 -m pytest tests/ -v --cov=src/workflow_scheduler"
    )
    assert scheduler_test_command in scheduler
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" in scheduler


def test_cloud_build_does_not_use_github_actions_cache_configuration():
    content = CLOUD_BUILD.read_text(encoding="utf-8")
    assert "actions/setup-python" not in content
    assert "cache-dependency-path" not in content
    assert 'cache: "pip"' not in content
