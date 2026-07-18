from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def test_validation_gate_executes_canonical_repository_commands():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" in content
    assert "./scripts/validate-all.sh" in content
    assert "Cloud Build validation migration notice" not in content


def test_validation_gate_uses_read_only_permissions_and_bounded_execution():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in content
    assert "contents: write" not in content
    assert "timeout-minutes: 30" in content
    assert "cancel-in-progress: true" in content


def test_validation_gate_installs_same_dependencies_as_cloud_build():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cloudbuild = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
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
