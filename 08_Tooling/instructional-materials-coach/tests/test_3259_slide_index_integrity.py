"""#3259 D1: duplicate or invalid slide indexes fail closed at parse time.

Two authored slides sharing an index used to silently erase the first
slide's placeholder tokens before terminal QA built its expectations
(false VERIFIED). content_from_dict() now canonicalizes each slide index
and rejects duplicates before the lossy dict conversion.
"""
import pytest

from instructional_materials_coach.content_spec import LessonContent, content_from_dict
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.slides_requests import build_slides_replace_requests


def _lesson(slides):
    return {
        "title": "Candy Branding",
        "objectives": ["Name the brand"],
        "slides": slides,
        "worksheet_questions": ["What is the brand promise?"],
    }


def _tokens_of(requests):
    return [r["replaceAllText"]["containsText"]["text"][2:-2] for r in requests]


def test_duplicate_int_indexes_rejected_before_token_conversion():
    with pytest.raises(ValueError, match="content-spec-duplicate-slide-index"):
        content_from_dict(_lesson([
            {"index": 1, "heading": "Alpha intro heading"},
            {"index": 1, "heading": "Beta outro heading"},
        ]))


def test_duplicate_error_names_both_slide_positions():
    with pytest.raises(ValueError, match="content-spec-duplicate-slide-index") as exc:
        content_from_dict(_lesson([
            {"index": 1, "heading": "Alpha"},
            {"index": 2, "heading": "Mid"},
            {"index": 1, "heading": "Beta"},
        ]))
    assert "slide #3" in str(exc.value)
    assert "slide #1" in str(exc.value)


def test_string_index_collides_with_int_index():
    # "1" vs 1 collide via f-string type erasure; canonicalization closes it.
    with pytest.raises(ValueError, match="content-spec-duplicate-slide-index"):
        content_from_dict(_lesson([
            {"index": "1", "heading": "Alpha"},
            {"index": 1, "heading": "Beta"},
        ]))


def test_missing_index_rejected_at_parse():
    # Previously: unhandled KeyError downstream of parse.
    with pytest.raises(ValueError, match="content-spec-slide-index-invalid"):
        content_from_dict(_lesson([{"heading": "Alpha"}]))


@pytest.mark.parametrize("bad", [True, None, 1.0, "", "  ", "abc", "1.5"])
def test_unusable_index_values_rejected(bad):
    with pytest.raises(ValueError, match="content-spec-slide-index-invalid"):
        content_from_dict(_lesson([{"index": bad, "heading": "Alpha"}]))


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_non_positive_index_rejected(bad):
    with pytest.raises(ValueError, match="content-spec-slide-index-invalid"):
        content_from_dict(_lesson([{"index": bad, "heading": "Alpha"}]))


def test_valid_distinct_indexes_preserve_every_slide():
    content = content_from_dict(_lesson([
        {"index": 1, "heading": "Alpha", "bullets": ["a1", "a2"]},
        {"index": 2, "heading": "Beta", "bullets": ["b1"]},
        {"index": 3, "heading": "Gamma"},
    ]))
    tokens = content.placeholder_tokens()
    assert tokens["slide_1_heading"] == "Alpha"
    assert tokens["slide_1_bullet_1"] == "a1"
    assert tokens["slide_1_bullet_2"] == "a2"
    assert tokens["slide_2_heading"] == "Beta"
    assert tokens["slide_2_bullet_1"] == "b1"
    assert tokens["slide_3_heading"] == "Gamma"
    # Every authored slide token reaches both production builders; no cross-talk.
    docs_requests = build_docs_replace_requests(content)
    slides_requests = build_slides_replace_requests(content)
    for token in ("slide_1_heading", "slide_1_bullet_1", "slide_1_bullet_2",
                  "slide_2_heading", "slide_2_bullet_1", "slide_3_heading"):
        assert _tokens_of(docs_requests).count(token) == 1
        assert _tokens_of(slides_requests).count(token) == 1


def test_string_index_canonicalized_without_rejection():
    # #3584 compatibility: int-or-numeric-string indexes stay accepted.
    content = content_from_dict(_lesson([{"index": "1", "heading": "Alpha"}]))
    assert content.placeholder_tokens()["slide_1_heading"] == "Alpha"


def test_valid_content_token_map_unchanged():
    # Valid content behaves exactly as before the repair.
    content = content_from_dict(_lesson([
        {"index": 1, "heading": "Welcome", "bullets": ["Hello"]},
    ]))
    assert content.placeholder_tokens() == {
        "title": "Candy Branding",
        "objective_1": "Name the brand",
        "slide_1_heading": "Welcome",
        "slide_1_bullet_1": "Hello",
        "question_1": "What is the brand promise?",
    }


def test_direct_construction_collision_guard():
    # placeholder_tokens() protects LessonContent built without
    # content_from_dict() (the parse-time gate is bypassed there).
    content = LessonContent(
        title="T", objectives=[],
        slides=[{"index": 1, "heading": "A"}, {"index": 1, "heading": "B"}],
        worksheet_questions=[],
    )
    with pytest.raises(ValueError, match="content-spec-token-collision"):
        content.placeholder_tokens()
