from pathlib import Path

from scripts.agent_os_issue_labels.pr_lifecycle import lifecycle_invocation_reasons


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "02_Agent_Overlays" / "github-service-agent.md"


def _overlay_text() -> str:
    return OVERLAY.read_text(encoding="utf-8")


def test_draft_pr_creation_requires_existing_managed_label_lifecycle_follow_up():
    text = _overlay_text()

    assert "Every successful authorized Draft PR creation must immediately perform" in text
    assert "`draft-pr-created`" in text
    assert "#1022 planner, #1023 reconciler, and #1038 lifecycle integration" in text
    assert "Reacquire the created PR and its exact live head SHA before label mutation" in text
    assert "Preserve every unmanaged, human, security, dependency, and third-party label" in text
    assert "Reread the PR after mutation and prove managed-label convergence" in text
    assert "already-converged rerun must perform zero label writes" in text
    assert "creation evidence separately from label-reconciliation result" in text
    assert "draft-pr-created" in lifecycle_invocation_reasons()


def test_draft_pr_label_follow_up_preserves_non_authority_and_excludes_unattended_triggers():
    text = _overlay_text()

    for authority in (
        "Ready-for-Review",
        "merge",
        "issue closure",
        "review resolution",
        "protected setting",
        "production",
        "external-system authority",
    ):
        assert authority in text

    for excluded_surface in (
        "GitHub Actions workflow",
        "webhook",
        "poller",
        "daemon",
        "background worker",
        "permission expansion",
        "repository-local PR-creation subsystem",
    ):
        assert excluded_surface in text
