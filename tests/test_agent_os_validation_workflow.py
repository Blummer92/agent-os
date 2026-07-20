from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"
SCHEDULER_WORKFLOW = ROOT / ".github/workflows/workflow-scheduler-validation.yml"
CLOUD_BUILD = ROOT / "cloudbuild.yaml"


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


def test_validation_gate_caches_all_installed_dependency_manifests():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/setup-python@v5" in content
    assert 'cache: "pip"' in content
    required_manifests = [
        "requirements-dev.txt",
        "08_Tooling/workflow-scheduler/requirements.txt",
        "08_Tooling/instructional-materials-coach/pyproject.toml",
        "08_Tooling/notion-navigation-client/pyproject.toml",
        "08_Tooling/reusable-capability-registry/pyproject.toml",
    ]
    for manifest in required_manifests:
        assert manifest in content


def test_scheduler_validation_uses_its_requirements_for_pip_cache():
    content = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/setup-python@v5" in content
    assert 'cache: "pip"' in content
    assert (
        "cache-dependency-path: 08_Tooling/workflow-scheduler/requirements.txt"
        in content
    )
    assert content.count("cache-dependency-path:") == 1
    assert "requirements-dev.txt" not in content
    assert "pyproject.toml" not in content


def test_cache_configuration_does_not_replace_install_or_validation_commands():
    aggregate = WORKFLOW.read_text(encoding="utf-8")
    scheduler = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements-dev.txt" in aggregate
    assert "./scripts/validate-all.sh" in aggregate
    assert (
        "python -m pip install -r 08_Tooling/workflow-scheduler/requirements.txt"
        in scheduler
    )
    assert "PYTHONPATH=src python3 -m pytest tests/ -v --cov=src/workflow_scheduler" in scheduler
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" in scheduler


def test_cloud_build_does_not_use_github_actions_cache_configuration():
    content = CLOUD_BUILD.read_text(encoding="utf-8")
    assert "actions/setup-python" not in content
    assert "cache-dependency-path" not in content
    assert 'cache: "pip"' not in content
