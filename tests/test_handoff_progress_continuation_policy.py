"""Regression guard for #1608: handoff creation is progress, not completion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "07_Agent_Tests/fixtures/handoff-progress-is-not-completion.md"
CONTRACT = ROOT / "01_Shared_Standards/github/tool-discovery-continuation.md"
MISSION_CONTINUITY = ROOT / "01_Shared_Standards/github/mission-continuity.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_live_1237_handoff_stop_is_pinned() -> None:
    fixture = normalized(FIXTURE)
    for phrase in (
        "Work on #1237",
        "Complete handoff",
        "durable #1237 handoff comment written",
        "assistant reports handoff complete and returns control to owner",
        "owner must ask why no PR exists / why work stopped",
    ):
        assert phrase in fixture


def test_handoff_artifact_is_intermediate_when_work_remains() -> None:
    fixture = normalized(FIXTURE)
    assert "handoff artifact created + unfinished finite mission != terminal completion" in fixture
    assert "continue through the GitHub Service Agent to branch, implementation, validation evidence, and one Draft PR" in fixture


def test_genuine_external_integration_blocker_does_not_fabricate_pr() -> None:
    fixture = normalized(FIXTURE)
    assert "do not fabricate a repository PR" in fixture
    assert "explicit terminal integration blocker" in fixture
    assert "unavailable implementation capability and clearing condition" in fixture


def test_existing_continuation_contract_remains_canonical() -> None:
    contract = normalized(CONTRACT)
    fixture = normalized(FIXTURE)
    assert "successful tool/capability discovery + unfinished authorized mission != terminal state" in contract
    assert "#1237 same-lineage continuation" in fixture
    assert "#1524 terminal reconciliation" in fixture
    assert "#1200 no-progress ownership" in fixture


def test_fixture_does_not_create_excluded_authority() -> None:
    fixture = normalized(FIXTURE)
    for phrase in (
        "merge",
        "issue closure",
        "workflow/protected-setting mutation",
        "credential/IAM",
        "production",
        "external-write",
        "native-product mutation",
    ):
        assert phrase in fixture


def test_3038_handoff_persistence_requires_parent_continuation() -> None:
    continuity = normalized(MISSION_CONTINUITY)
    for phrase in (
        "handoff, evidence comment, bug record, route discovery, or bounded investigation checkpoint is intermediate",
        "reacquire the parent issue",
        "consume the already-identified capable route or bounded evidence gate",
        "one canonically read-back Draft PR",
    ):
        assert phrase in continuity


def test_3038_does_not_require_owner_to_repeat_continuation_phrases() -> None:
    continuity = normalized(MISSION_CONTINUITY)
    for phrase in (
        "complete the handoff",
        "make the PR",
        "repeat `work on`",
        "merely because the previous operation persisted a handoff",
    ):
        assert phrase in continuity


def test_3038_cleared_blocker_cannot_be_reused_as_terminal_disposition() -> None:
    continuity = normalized(MISSION_CONTINUITY)
    assert "current evidence proves cleared is no longer a terminal disposition" in continuity
    assert "rather than returning the stale blocker again" in continuity


def test_3038_preserves_real_gates_and_existing_authority_ceiling() -> None:
    continuity = normalized(MISSION_CONTINUITY)
    for phrase in (
        "does not bypass a genuine compatibility, authorization, source-of-truth, excluded-surface, or material-decision gate",
        "does not turn a handoff into implementation authority",
        "only authority already present in the current parent mission",
    ):
        assert phrase in continuity
