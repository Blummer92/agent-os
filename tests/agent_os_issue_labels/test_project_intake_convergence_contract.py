from scripts.agent_os_issue_labels.connected_issue_creation import ConnectedIssueCreationConvergence


def intake_classified(result: ConnectedIssueCreationConvergence) -> bool:
    """Project/intake may treat an issue as classified only after convergence."""
    return result.terminal_success and result.reconciliation.convergence_status in {"converged", "already-current"}


def test_zero_label_preconvergence_issue_is_not_classified():
    class Reconciliation:
        convergence_status = "would-change"
    result = ConnectedIssueCreationConvergence("Blummer92/agent-os", 2236, (), Reconciliation(), False, ("connected-create-label-convergence-not-proven",))
    assert intake_classified(result) is False


def test_converged_issue_is_classified():
    class Reconciliation:
        convergence_status = "converged"
    result = ConnectedIssueCreationConvergence("Blummer92/agent-os", 2236, ("agent-os", "owner:github-service-agent", "status:ready", "type:bug"), Reconciliation(), True, ("connected-create-label-convergence-proven",))
    assert intake_classified(result) is True


def test_manual_review_remains_fail_closed():
    class Reconciliation:
        convergence_status = "manual-review"
    result = ConnectedIssueCreationConvergence("Blummer92/agent-os", 2236, (), Reconciliation(), False, ("connected-create-label-convergence-not-proven",))
    assert intake_classified(result) is False
