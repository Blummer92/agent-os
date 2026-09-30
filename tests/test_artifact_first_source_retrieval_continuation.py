"""Regression guards for #3103: source retrieval must continue into worksheet generation.

On 2026-09-29 a teacher asked for a Photography Foundations worksheet; source
retrieval succeeded and the DOCX skill was loaded, but the response stopped
before producing the worksheet. Source retrieval is intermediate evidence, not
a terminal response.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_FIRST = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"

# Exact regression fixture from the #3103 2026-09-29 reproduction. Fixture
# identities are not canonical curriculum content.
ISSUE_3103_REQUEST = (
    "Make me a worksheet for my photography class where students take five "
    "different pictures of the same object. Use the Photography Foundations "
    "materials already in this project."
)


def normalized() -> str:
    return " ".join(ARTIFACT_FIRST.read_text(encoding="utf-8").split())


def test_3103_regression_fixture_is_a_bounded_worksheet_request() -> None:
    assert "worksheet" in ISSUE_3103_REQUEST
    assert "five different pictures of the same object" in ISSUE_3103_REQUEST
    assert "Photography Foundations" in ISSUE_3103_REQUEST
    assert "materials already in this project" in ISSUE_3103_REQUEST


def test_3103_source_retrieval_is_intermediate_not_terminal() -> None:
    text = ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert "## Source Retrieval Delivery Continuation" in text
    standard = normalized()
    for phrase in (
        "A successful project/source retrieval is intermediate evidence",
        "that artifact has not yet been produced",
        "Do not stop at retrieval merely to report",
        "Loading a DOCX-generation skill or summarizing retrieved composition concepts"
        " is not worksheet delivery",
    ):
        assert phrase in standard


def test_3103_continues_into_generation_before_backend_reporting() -> None:
    standard = normalized()
    for phrase in (
        "continue immediately into worksheet generation",
        "treat the retrieved source context as input to production, not as the"
        " response's terminal deliverable",
        "produce the usable student-facing worksheet artifact, or complete"
        " artifact-ready student-facing content",
        "before backend status or governance reporting",
    ):
        assert phrase in standard


def test_3103_project_materials_are_consumed_without_repetition() -> None:
    standard = normalized()
    assert (
        "consume the retrieved project materials and composition vocabulary directly,"
        " without requiring the teacher to restate what the project already contains"
        in standard
    )


def test_3103_bounded_local_chat_artifact_without_drive_destination() -> None:
    standard = normalized()
    assert "when no explicit Drive destination is supplied" in standard
    assert (
        "finish with a bounded local/chat artifact -- complete student-facing worksheet"
        " content or a clearly labeled content specification" in standard
    )


def test_3103_no_unnecessary_clarifying_question_when_materials_sufficient() -> None:
    standard = normalized()
    assert (
        "Do not ask an unnecessary clarifying question when the supplied project"
        " materials are sufficient for a bounded worksheet" in standard
    )


def test_3103_no_github_lesson_artifact_write() -> None:
    text = normalized().lower()
    assert "a missing drive destination never authorizes writing the lesson artifact to github" in text


def test_3103_preserves_source_grounding_and_destinations() -> None:
    text = normalized().lower()
    for phrase in (
        "does not change classroom artifact destinations",
        "does not authorize drive, notion, publication, or other external writes",
        "does not weaken source-grounding requirements",
    ):
        assert phrase in text


def test_3103_artifact_first_ordering_still_required() -> None:
    standard = normalized()
    assert "## Required Order" in ARTIFACT_FIRST.read_text(encoding="utf-8")
    assert (
        "Lead the response with the requested artifact, or a clearly labeled"
        " preview or content specification of it" in standard
    )


def test_3103_standard_version_covers_source_retrieval_continuation() -> None:
    text = ARTIFACT_FIRST.read_text(encoding="utf-8")
    version_block = text.split("## Version", 1)[1]
    version = version_block.strip().splitlines()[0]
    major, minor, patch = (int(part) for part in version.split("."))
    assert (major, minor, patch) >= (0, 1, 7)
