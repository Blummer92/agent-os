from pathlib import Path


OVERLAY = Path("02_Agent_Overlays/github-service-agent.md")


def test_implementation_issue_creation_requires_canonical_classification_readback():
    text = OVERLAY.read_text(encoding="utf-8")
    section = text.split("## Implementation-Issue Post-Create Classification And Continuation", 1)[1]
    section = section.split("## Repository-State Verification", 1)[0]
    assert "creation response as provisional" in section
    assert "canonical issue readback" in section
    assert "managed classification labels" in section
    assert "structured issue-create path" in section
    assert "validated `proposed_labels`" in section
    assert "#1962 issue-label reconciler" in section
    assert "Never infer `status:ready`" in section
    assert "carry that same instruction forward" in section


def test_post_create_contract_preserves_authority_separation():
    text = OVERLAY.read_text(encoding="utf-8")
    section = text.split("## Implementation-Issue Post-Create Classification And Continuation", 1)[1]
    section = section.split("## Repository-State Verification", 1)[0]
    assert "Label convergence is a projection" in section
    for authority in ("merge", "closure", "protected-setting", "production", "credential", "external-write"):
        assert authority in section
