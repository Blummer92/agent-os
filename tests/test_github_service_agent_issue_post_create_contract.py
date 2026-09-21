from pathlib import Path


OVERLAY = Path("02_Agent_Overlays/github-service-agent.md")
ORCHESTRATOR = Path("02_Agent_Overlays/chatgpt-orchestrator.md")


def test_every_agent_os_issue_creation_requires_canonical_classification_readback():
    text = OVERLAY.read_text(encoding="utf-8")
    section = text.split("## Agent OS Issue Post-Create Classification And Continuation", 1)[1]
    section = section.split("## Repository-State Verification", 1)[0]
    assert "creation response as provisional" in section
    assert "canonical issue readback" in section
    assert "managed classification labels" in section
    assert "structured issue-create path" in section
    assert "validated `proposed_labels`" in section
    assert "#1962 issue-label reconciler" in section
    assert "Never infer `status:ready`" in section
    assert "carry that same instruction forward" in section
    assert "any Agent OS issue" in section
    assert "bug capture" in section
    assert "testing/planning issues" in section
    assert "direct/native connected create response" in section
    assert "before the create operation can become terminal" in section


def test_post_create_contract_preserves_authority_separation():
    text = OVERLAY.read_text(encoding="utf-8")
    section = text.split("## Agent OS Issue Post-Create Classification And Continuation", 1)[1]
    section = section.split("## Repository-State Verification", 1)[0]
    assert "Label convergence is a projection" in section
    for authority in ("merge", "closure", "protected-setting", "production", "credential", "external-write"):
        assert authority in section


def test_orchestrator_requires_universal_issue_create_convergence():
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    for phrase in (
        "every authorized Agent OS issue creation",
        "canonical connected issue-creation/managed-label contract",
        "native/direct GitHub create response as provisional",
        "planned managed labels have converged through the existing #1962 reconciler",
        "Missing or partial managed labels are intermediate state, not terminal success",
        "bug capture",
        "testing/planning issues",
        "focused successors",
        "self-defect creation",
    ):
        assert phrase in text


def test_universal_issue_create_convergence_preserves_authority_separation():
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "adds no second label writer or authority system" in text
