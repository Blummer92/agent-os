"""Regression for #3152: interrupted retrieval in a finite artifact mission stays intermediate.

A client/streaming interruption (or a source-retrieval tool call that ends with
no consumed result) during a finite classroom-artifact mission must be governed
as an intermediate retrieval boundary -- never mission completion -- with the
artifact-mission plan state preserved and resumed from the last completed
operation boundary when the host permits re-entry.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"

SECTION_MARKER = "### Interrupted retrieval in finite artifact missions\n"


def read_section() -> str:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert SECTION_MARKER in text, "missing interrupted-retrieval subsection"
    return text.split(SECTION_MARKER, 1)[1].split("\n## ", 1)[0]


def test_interruption_is_intermediate_retrieval_boundary_not_completion() -> None:
    section = read_section()
    assert "intermediate retrieval boundary" in section
    assert "not mission completion" in section
    assert "not by itself failure evidence" in section


def test_last_completed_operation_correlated_and_result_classified() -> None:
    section = read_section()
    assert "last successfully completed operation" in section
    for classification in ("pending", "returned-but-unconsumed", "never returned"):
        assert classification in section


def test_artifact_mission_plan_state_preserved() -> None:
    section = read_section()
    assert "artifact-mission plan state" in section
    assert "retrieval cursor" in section
    assert "canonical evidence already gathered" in section
    for phase in (
        "source retrieval",
        "instructional decisions",
        "visual/source reconciliation",
        "artifact generation",
        "artifact verification",
        "final delivery/report",
    ):
        assert phase in section


def test_resume_from_last_completed_boundary_without_new_owner_prompt() -> None:
    section = read_section()
    assert "resume from the last completed operation boundary" in section
    assert "re-issue only the uncompleted retrieval step" in section
    assert "do not reprocess completed phases" in section
    assert "do not require a new owner prompt" in section


def test_no_callable_continuation_reports_exact_blocker() -> None:
    section = read_section()
    assert "report that exact native continuation capability as the blocker" in section


def test_reuses_existing_continuation_architecture_without_new_framework() -> None:
    section = read_section()
    assert "#2826" in section
    assert "existing finite-mission cursor" in section
    for forbidden in ("scheduler", "queue", "mission store", "polling loop"):
        assert forbidden in section


def test_changelog_records_issue_3152() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "## Version\n0.3.18" in text
    assert "#3152" in text
