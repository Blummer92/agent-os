"""Conformance guards for #1726 routine repository-coding hot path."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "01_Shared_Standards/github/routine-repository-coding-hot-path.md"
SAFE_LANE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_minimum_hot_path_is_explicit() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "canonical request interpretation",
        "live issue + existing lineage acquisition",
        "Safe Implementation Lane / IssueOperationalState admission",
        "connector-native execution when sufficient",
        "bounded implementation",
        "Draft PR",
        "one authoritative exact-head aggregate",
        "final PR/head/review reconciliation",
    ):
        assert phrase in contract


def test_optional_mechanisms_are_lazy() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "retrieval_required=false` means zero Decision reads",
        "retrieval_required=false` means zero Lessons Learned reads",
        "only for an existing resumable execution lineage",
        "only for governed runtime/concurrency execution",
        "only for proven behind/diverged base state",
        "only for actual CI/review repair",
        "only for an explicit finite multi-item mission",
        "only for the canonical structured `operating-mode=release` request",
        "only when canonical request/context evidence resolves there",
    ):
        assert phrase in contract


def test_hot_path_reuses_existing_authority_and_freshness_owners() -> None:
    contract = normalized(CONTRACT)
    safe_lane = normalized(SAFE_LANE)
    orchestrator = normalized(ORCHESTRATOR)
    assert "Do not introduce a new cache or Task State Capsule" in contract
    assert "Only required evidence bound to the current exact head may satisfy Ready-for-Review" in safe_lane
    assert "Route repository writes only to the GitHub Service Agent" in orchestrator
    assert "GitHub Service Agent remains sole repository writer" in contract


def test_routine_path_excludes_nonroutine_states() -> None:
    contract = normalized(CONTRACT)
    for phrase in (
        "no active/ambiguous Scheduler lease",
        "no resume/checkpoint lineage requiring recovery",
        "no branch-behind/diverged condition requiring governed refresh",
        "no red-CI/review remediation state",
        "no release-mode request",
        "no finite multi-item mission",
        "no classroom/PPUX routing requirement",
    ):
        assert phrase in contract
