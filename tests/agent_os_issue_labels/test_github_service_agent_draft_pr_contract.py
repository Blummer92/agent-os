from pathlib import Path

from scripts.agent_os_issue_labels.pr_lifecycle import lifecycle_invocation_reasons


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "02_Agent_Overlays" / "github-service-agent.md"
VERSION_MAP = ROOT / "04_Registry" / "module-version-map.md"


def _overlay_text() -> str:
    return OVERLAY.read_text(encoding="utf-8")


def test_draft_pr_creation_requires_existing_managed_label_lifecycle_follow_up():
    text = _overlay_text()

    for required in (
        "After every successful authorized Draft PR creation",
        "`draft-pr-created`",
        "#1022/#1023/#1038",
        "planner-derived managed-label delta",
        "preserve unmanaged/human/security/dependency/third-party labels",
        "reread to prove convergence",
        "zero label writes on an unchanged converged rerun",
        "creation evidence separate from label-reconciliation evidence",
    ):
        assert required in text
    assert "draft-pr-created" in lifecycle_invocation_reasons()


def test_draft_pr_label_follow_up_preserves_non_authority_and_excludes_unattended_triggers():
    text = _overlay_text()

    for required in (
        "Ready-for-Review",
        "merge",
        "issue-closure",
        "review-resolution",
        "protected-setting",
        "production",
        "external-system authority",
        "GitHub Actions workflow",
        "webhook",
        "poller",
        "daemon",
        "background worker",
        "permission expansion",
        "repository-local PR-creation subsystem",
    ):
        assert required in text


def test_github_service_agent_version_is_registered():
    version_map = VERSION_MAP.read_text(encoding="utf-8")
    assert "| GitHub Service Agent | 0.8.0 |" in version_map
