"""#3582: enforceable offline no-write worksheet content preview.

The preview exercises the real authored-YAML -> lesson-content adapter ->
Docs request composition with the pinned live run 38462963519 evidence. It
must never request credentials, build a Google client, run the live builder,
write a lesson record, or claim a rendered/native/classroom-ready artifact.
Authored lesson text here is fixture text only, used to prove preservation.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from instructional_materials_coach import cli
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.lesson_content_result import LessonContentSelection
from instructional_materials_coach.worksheet_preview import PREVIEW_CONTRACT, preview_lesson_worksheet

LIVE_FIXTURE = Path(__file__).parent / "fixtures" / "lesson_content_run_38462963519.json"
UNIT_PAGE_ID = "3907ac78-3131-8132-8f84-f9fd633acba5"
DAY1_TARGET = "I can choose colors on purpose and explain how they match the candy mood and audience."
DAY1_FOCUS = "Plan intentional candy color choices before software use."
SELECTION = LessonContentSelection(
    request_id="candy-branding-lesson-content",
    canonical_unit_page_id=UNIT_PAGE_ID,
    day_lesson_number="Day 1",
    generated_at="38462963519:1",
)
AUTHORED = {
    "title": "Fixture lesson title",
    "objectives": [],
    # Independent authored lesson-identity binding required for the
    # empty-objectives fill; the title is never the matching rule.
    "lesson_identity": {"day_lesson_number": "Day 1"},
    "slides": [{"index": 1, "heading": "Fixture slide heading", "bullets": ["Fixture bullet"]}],
    "worksheet_questions": ["Fixture question one?", "Fixture question two?"],
}
CLIENT_BOUNDARY = (
    "get_credentials",
    "build_drive_service",
    "build_slides_service",
    "build_docs_service",
    "build_live_materials",
    "build_placement_transport",
    "get_file_metadata",
    "record_lesson",
)


def _evidence() -> dict:
    return json.loads(LIVE_FIXTURE.read_text(encoding="utf-8"))


def _content(**overrides):
    return content_from_dict({**AUTHORED, **overrides})


@contextlib.contextmanager
def _no_client_boundary():
    """Every connected/credential/lesson-record seam raises if touched."""
    with contextlib.ExitStack() as stack:
        mocks = [
            stack.enter_context(
                patch(f"instructional_materials_coach.cli.{name}", side_effect=AssertionError(f"{name} reached"))
            )
            for name in CLIENT_BOUNDARY
        ]
        yield mocks


def _cli_args(tmp_path: Path, *, lesson: str = "Day 1", authored: dict | None = None) -> list[str]:
    content = tmp_path / "lesson.yaml"
    content.write_text(yaml.safe_dump(authored or AUTHORED), encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(LIVE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return [
        "preview-worksheet",
        "--content", str(content),
        "--lesson-content-result", str(result),
        "--request-id", "candy-branding-lesson-content",
        "--canonical-unit-page-id", UNIT_PAGE_ID,
        "--lesson", lesson,
        "--generated-at", "38462963519:1",
        "--preview-out", str(tmp_path / "preview.json"),
    ]


def test_live_day1_preview_plans_verified_lesson_and_authored_questions() -> None:
    receipt = preview_lesson_worksheet(_content(), _evidence(), SELECTION)

    assert receipt["contract_version"] == PREVIEW_CONTRACT
    assert receipt["status"] == "preview"
    assert receipt["reason_code"] is None
    assert receipt["lesson"] == {
        "request_id": "candy-branding-lesson-content",
        "generated_at": "38462963519:1",
        "logical_source": "daily-generation-packet",
        "verification_state": "verified-current",
        "canonical_unit_page_id": UNIT_PAGE_ID,
        "day_lesson_number": "Day 1",
        "record_url": "https://app.notion.com/p/Candy-Branding-Design-Day-1-Color-Planning-3717ac7831318135ae7cf2ead0cf28ac",
        "source_evidence": (
            "Candy Brand Design source says Day 1 establishes intentional color planning before "
            "software use and portfolio checklist includes candy concept plus labeled palettes."
        ),
    }
    worksheet = receipt["worksheet"]
    assert worksheet["learning_target"] == DAY1_TARGET
    assert worksheet["daily_focus"] == DAY1_FOCUS
    assert worksheet["key_vocabulary"] is None
    assert worksheet["objectives"] == [DAY1_TARGET, DAY1_FOCUS]
    assert worksheet["objective_source"] == "governed-lesson-content"
    assert worksheet["questions"] == AUTHORED["worksheet_questions"]
    planned = {item["token"]: item["text"] for item in worksheet["planned_replacements"]}
    assert planned["question_1"] == "Fixture question one?"
    assert planned["question_2"] == "Fixture question two?"
    assert planned["context_lesson_learning_target"] == DAY1_TARGET
    assert not [token for token in planned if "vocab" in token]
    assert all(receipt["checks"].values())


def test_preview_never_claims_render_native_artifact_readiness_or_authority() -> None:
    receipt = preview_lesson_worksheet(_content(), _evidence(), SELECTION)
    assert receipt["preview_kind"] == "planned-worksheet-content"
    assert receipt["rendered"] is False
    assert receipt["native_artifact"] is None
    assert receipt["classroom_ready"] is False
    assert set(receipt["side_effects"].values()) == {False}
    assert set(receipt["authority"].values()) == {False}


def test_preview_is_deterministic() -> None:
    first = preview_lesson_worksheet(_content(), _evidence(), SELECTION)
    second = preview_lesson_worksheet(_content(), _evidence(), SELECTION)
    assert first == second
    assert len(first["worksheet"]["planned_content_sha256"]) == 64


def test_blocked_preview_carries_reason_and_no_planned_content() -> None:
    evidence = _evidence()
    evidence["result"]["lessons"][0]["canonical_unit"]["page_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    receipt = preview_lesson_worksheet(_content(), evidence, SELECTION)
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "unit-mismatch"
    assert receipt["worksheet"] is None
    assert receipt["lesson"] is None


def test_unresolved_token_in_authored_copy_blocks_preview() -> None:
    receipt = preview_lesson_worksheet(
        _content(worksheet_questions=["Fixture {{unresolved}} question?"]), _evidence(), SELECTION
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "preview-check-failed"
    assert receipt["checks"]["no_unresolved_tokens"] is False
    assert receipt["worksheet"] is None


@pytest.mark.parametrize("allow_write", [None, "true"])
def test_cli_preview_is_offline_and_no_write_even_with_allow_write(tmp_path, monkeypatch, allow_write) -> None:
    if allow_write is None:
        monkeypatch.delenv("ALLOW_WRITE", raising=False)
    else:
        monkeypatch.setenv("ALLOW_WRITE", allow_write)
    args = _cli_args(tmp_path)
    with _no_client_boundary() as mocks:
        assert cli.main(args) == 0
    assert not any(mock.called for mock in mocks)
    receipt = json.loads((tmp_path / "preview.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "preview"
    assert receipt["worksheet"]["learning_target"] == DAY1_TARGET
    assert sorted(path.name for path in tmp_path.iterdir()) == ["lesson.yaml", "preview.json", "result.json"]


def test_cli_preview_blocks_wrong_lesson_and_still_writes_nothing_external(tmp_path) -> None:
    authored = {**AUTHORED, "objectives": [DAY1_TARGET]}
    args = _cli_args(tmp_path, lesson="Day 3", authored=authored)
    with _no_client_boundary() as mocks:
        assert cli.main(args) == 1
    assert not any(mock.called for mock in mocks)
    receipt = json.loads((tmp_path / "preview.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "objective-conflict"


def test_cli_preview_rejects_unreadable_and_oversized_input(tmp_path, monkeypatch) -> None:
    args = _cli_args(tmp_path)
    missing = list(args)
    missing[missing.index("--lesson-content-result") + 1] = str(tmp_path / "absent.json")
    with _no_client_boundary():
        assert cli.main(missing) == 1
    monkeypatch.setattr(cli, "MAX_LESSON_CONTENT_RESULT_BYTES", 16)
    with _no_client_boundary():
        assert cli.main(args) == 1
    assert not (tmp_path / "preview.json").exists()


# ---------------------------------------------------------------------------
# #3584 repair regressions: CLI input boundary (byte bound, YAML, deep JSON)
# ---------------------------------------------------------------------------


def _write_result(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_args(tmp_path: Path, content_text: str, result_path: Path) -> list[str]:
    content = tmp_path / "lesson.yaml"
    content.write_text(content_text, encoding="utf-8")
    return [
        "preview-worksheet",
        "--content", str(content),
        "--lesson-content-result", str(result_path),
        "--request-id", "candy-branding-lesson-content",
        "--canonical-unit-page-id", UNIT_PAGE_ID,
        "--lesson", "Day 1",
        "--generated-at", "38462963519:1",
        "--preview-out", str(tmp_path / "preview.json"),
    ]


def _nested_list(depth: int) -> list:
    root: list = []
    current = root
    for _ in range(depth):
        child: list = []
        current.append(child)
        current = child
    return root


def test_cli_byte_bound_enforced_on_actual_bytes(tmp_path, monkeypatch) -> None:
    """The bound applies to the bytes read, not a pre-read stat()."""
    import instructional_materials_coach.cli as cli_module

    payload = json.dumps(_evidence()["result"])
    assert len(payload.encode("utf-8")) > 64
    args = _cli_args(tmp_path)
    result = Path(args[args.index("--lesson-content-result") + 1])
    result.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(cli_module, "MAX_LESSON_CONTENT_RESULT_BYTES", len(payload.encode("utf-8")))
    with _no_client_boundary():
        assert cli.main(args) == 0
    monkeypatch.setattr(cli_module, "MAX_LESSON_CONTENT_RESULT_BYTES", len(payload.encode("utf-8")) - 1)
    with _no_client_boundary():
        assert cli.main(args) == 1


@pytest.mark.parametrize(
    "content_text",
    [
        "title: [unclosed\nobjectives: [",
        "",
        "just a scalar string",
        "42",
        "- a\n- list\n",
        "title: T\nobjectives: []\nslides:\n  - index: 1\nworksheet_questions: Why?\n",
    ],
)
def test_cli_malformed_yaml_fails_controlled(tmp_path, content_text) -> None:
    """Malformed/null/scalar YAML is blocked (input-unreadable), not a traceback."""
    args = _base_args(tmp_path, content_text, _write_result(tmp_path, _evidence()["result"]))
    with _no_client_boundary():
        assert cli.main(args) == 1
    assert not (tmp_path / "preview.json").exists()


def test_cli_deeply_nested_result_json_fails_controlled(tmp_path) -> None:
    """Deep JSON nesting is blocked, never an uncaught RecursionError."""
    args = _base_args(tmp_path, yaml.safe_dump(AUTHORED), _write_result(tmp_path, _nested_list(5000)))
    with _no_client_boundary():
        assert cli.main(args) == 1


def test_cli_scalar_questions_never_produce_a_mangled_preview(tmp_path) -> None:
    authored = dict(AUTHORED)
    authored["worksheet_questions"] = "Why?"
    args = _base_args(tmp_path, yaml.safe_dump(authored), _write_result(tmp_path, _evidence()["result"]))
    with _no_client_boundary():
        assert cli.main(args) == 1
    assert not (tmp_path / "preview.json").exists()


def test_blocked_receipt_never_claims_readiness_or_side_effects(tmp_path) -> None:
    """Failure receipts stay non-authorizing: defect-8 block carries no grant."""
    authored = {k: v for k, v in AUTHORED.items() if k != "lesson_identity"}
    args = _cli_args(tmp_path, authored=authored)
    with _no_client_boundary():
        assert cli.main(args) == 1
    receipt = json.loads((tmp_path / "preview.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "authored-identity-missing"
    assert receipt["worksheet"] is None
    assert receipt["rendered"] is False
    assert receipt["native_artifact"] is None
    assert receipt["classroom_ready"] is False
    assert set(receipt["side_effects"].values()) == {False}
    assert set(receipt["authority"].values()) == {False}
