"""CKR PR-2: CKR5 future_use_hints survive to the reviewable catalog-draft
boundary as proposed, non-authoritative applicability hints.

The hints travel on the lesson proposal only. They never enter
``catalog_entry_draft`` properties (the Notion-bound surface), never become
verified applicability evidence, and never change Status or
Surface Before Work governance.
"""

from __future__ import annotations

from agent_os_execution_service import ckr6_github_bridge as bridge


def candidate(**changes):
    value = {
        "source_reference": "PR #3392 repair",
        "signal": "repeated-repair",
        "failure_signature": "issue-creation-path-skips-label-plan",
        "ecosystem": "agent-os",
        "capability_kind": "failure-avoidance",
        "lesson_summary": "Every issue-creation path must consume the canonical label plan",
        "what_happened": "Two repairs failed because one host creation path skipped the label plan.",
        "severity": "High",
        "owner_agent": "github-service-agent",
        "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
        "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
        "what_to_do_next_time": "Route every creation path through the label plan and read labels back.",
        "guardrail": "Terminal success requires label convergence by readback.",
        "reusable_rule_proven": True,
        "future_use_hints": ["label plan", "issue creation"],
    }
    value.update(changes)
    return value


def capture(monkeypatch, **changes):
    monkeypatch.setattr(
        bridge,
        "resolve_lesson_read_route",
        lambda: (_ for _ in ()).throw(AssertionError("capture must not read")),
    )
    envelope = bridge.parse_envelope({
        "operation": "lesson-candidate",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "candidate": candidate(**changes),
    })
    assert bridge.classify_envelope(envelope)["retrieval_required"] is False
    return bridge.execute_envelope(envelope, retrieval_required=False)


def test_capture_proposal_carries_proposed_applicability_hints(monkeypatch):
    result = capture(monkeypatch)
    assert result["status"] == "reusable-new"
    proposal = result["lesson_proposal"]
    assert proposal["proposed_applicability_hints"] == ["issue creation", "label plan"]
    # Hints are proposals only: nothing about authority changes.
    assert proposal["authority_created"] is False
    assert proposal["notion_write_performed"] is False
    assert proposal["publication_authorized"] is False


def test_capture_hints_never_enter_catalog_entry_draft_properties(monkeypatch):
    result = capture(monkeypatch)
    draft = result["lesson_proposal"]["catalog_entry_draft"]
    assert "proposed_applicability_hints" not in draft["properties"]
    assert "future_use_hints" not in draft["properties"]
    assert set(draft["properties"]) == {
        "Lesson Learned",
        "What Happened",
        "What To Do Next Time",
        "Guardrail",
        "Learning Type",
        "Source Link",
    }
    assert {"Status", "Surface Before Work?"}.isdisjoint(draft["properties"])


def test_capture_without_hints_carries_empty_proposals(monkeypatch):
    result = capture(monkeypatch, future_use_hints=[])
    proposal = result["lesson_proposal"]
    assert proposal["proposed_applicability_hints"] == []
    # No hints means no surface-before-work recommendation (CKR5 rule).
    assert proposal["surface_before_work_recommendation"] is False


def test_capture_hints_do_not_become_verified_evidence(monkeypatch):
    # The proposal carries no applicability record, no reviewed mechanism,
    # and no verified observation: hints alone prove nothing.
    result = capture(monkeypatch)
    proposal = result["lesson_proposal"]
    assert "applicability_record" not in proposal
    assert "verified_mechanism" not in proposal
    assert proposal["proposed_applicability_hints"] == ["issue creation", "label plan"]
