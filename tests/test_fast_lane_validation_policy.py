from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTING = ROOT / "01_Shared_Standards/global-engineering/testing-and-release.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def normalized_text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def normalized_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}"
    start = text.index(marker) + len(marker)
    remainder = text[start:]
    end = remainder.find("\n## ")
    section = remainder if end == -1 else remainder[:end]
    return " ".join(section.split())


def test_validation_obligation_is_separate_from_execution_location() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "Validation obligation and validation execution location are separate decisions." in developer_loop
    assert "it is not inherently a local/manual or pre-Draft-PR command" in developer_loop
    assert "it is not inherently a local/manual pre-Draft-PR command" in lane


def test_local_executor_remains_preferred_when_capable() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "Prefer the active/local execution surface when it can run them safely" in developer_loop
    assert "Prefer the active/local route when available" in lane
    assert "reuse the canonical executor-routing contract" in lane


def test_governed_ci_can_stage_required_validation_after_draft_creation() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "Draft PR creation may stage that CI-routed validation" in developer_loop
    assert "A Draft PR may therefore exist while CI-routed developer-loop evidence is pending" in developer_loop
    assert "Draft PR creation may stage the validation" in lane
    assert "Do not require the user to copy/paste shell commands" in lane


def test_no_capable_executor_still_requires_decision() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "stop with `needs-decision`" in developer_loop
    assert "stop with `needs-decision`" in lane


def test_exact_head_evidence_is_required_for_ready_for_review() -> None:
    authoritative = normalized_section(TESTING, "Authoritative Final Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "CI evidence from any SHA other than the current required head is stale" in authoritative
    assert "Ready-for-Review" in authoritative
    assert "Only required evidence bound to the current exact head may satisfy Ready-for-Review" in lane
    assert "stale-head CI is insufficient" in lane


def test_exact_head_ci_may_subsume_focused_and_aggregate_obligations() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    authoritative = normalized_section(TESTING, "Authoritative Final Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "exact-head governed CI aggregate may provide both the required focused behavior evidence and the authoritative final aggregate evidence" in developer_loop
    assert "One clean aggregate run bound to the exact final pull-request head may satisfy the full-suite requirement" in authoritative
    assert "one clean exact-head aggregate may satisfy both obligations without duplicate local execution" in lane


def test_ci_routing_does_not_grant_lifecycle_or_external_authority() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    for phrase in (
        "Ready-for-Review",
        "merge",
        "closure",
        "production",
        "credential",
        "permission",
        "external-write",
    ):
        assert phrase in developer_loop
    assert "A CI-routed pending state grants no Ready-for-Review or later authority" in lane


def test_current_draft_ready_aggregate_trigger_policy_is_preserved() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    lane = normalized_section(SAFE_LANE, "Validation Loop")

    assert "types: [opened, reopened, synchronize, ready_for_review]" in workflow
    assert "github.event.pull_request.draft == false" in workflow
    assert "workflow_dispatch:" in workflow
    assert "this lane does not require aggregate validation on ordinary Draft PR updates" in lane
    assert "does not create or modify a workflow to obtain validation" in lane


def test_broader_local_validation_remains_available_for_diagnosis() -> None:
    developer_loop = normalized_section(TESTING, "Developer Loop Validation")

    assert (
        "Expand local testing when focused tests fail, when exact-head CI reports a "
        "specific failure that needs diagnosis, when CI is unavailable, or when the "
        "governing issue explicitly requires broader local validation."
    ) in developer_loop
