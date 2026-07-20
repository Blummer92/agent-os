from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"
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
