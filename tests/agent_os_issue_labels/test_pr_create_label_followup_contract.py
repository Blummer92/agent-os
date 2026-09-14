from pathlib import Path

OVERLAY = Path("02_Agent_Overlays/github-service-agent.md").read_text(encoding="utf-8")


def section(name: str) -> str:
    start = OVERLAY.index(f"## {name}")
    end = OVERLAY.find("\n## ", start + 3)
    return OVERLAY[start:] if end == -1 else OVERLAY[start:end]


def test_draft_pr_creation_requires_canonical_readback_before_label_followup():
    text = section("Draft-PR Post-Create Verification And Managed-Label Follow-Up")
    assert "After every successful authorized Draft PR creation" in text
    assert "Immediately reacquire the exact PR from canonical GitHub state" in text
    assert "Only after canonical post-create verification succeeds" in text


def test_pr_label_followup_reuses_existing_managed_lifecycle():
    text = section("Draft-PR Post-Create Verification And Managed-Label Follow-Up")
    assert "#1022/#1023/#1038 managed-label lifecycle" in text
    assert "draft-pr-created" in text
    assert "preserve unmanaged" in text
    assert "zero label writes on an unchanged converged rerun" in text


def test_label_convergence_never_grants_terminal_authority():
    text = section("Draft-PR Post-Create Verification And Managed-Label Follow-Up")
    for phrase in ("Ready-for-Review", "merge", "issue-closure", "production", "external-system authority"):
        assert phrase in text
