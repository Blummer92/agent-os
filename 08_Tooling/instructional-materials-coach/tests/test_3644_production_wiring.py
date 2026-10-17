"""#3644 (#3213): the teacher-voice screen is wired into the production build path.

The regression exercises the real production caller chain, not the scanner
in isolation: ``build_docs_replace_requests`` is the exact function
``cli.py build`` uses to turn lesson content into worksheet replace
requests, and ``compose_governed_build_request`` is the exact function it
passes them to (also the composition behind ``live_build_input_factory``
for scheduled consumers). A leak fails closed in the composer -- no
``LiveBuildInput`` is returned, so no Drive write can happen.
"""
import pytest

from instructional_materials_coach.build_request import compose_governed_build_request
from instructional_materials_coach.content_spec import LessonContent
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.student_voice import StudentVoiceError


def _content(*, question: str, title: str = "Photography foundations") -> LessonContent:
    return LessonContent(
        title=title,
        objectives=["Notice light and shadow"],
        slides=[{"index": 1, "heading": "See the light", "bullets": ["Look at the window"]}],
        worksheet_questions=[question],
    )


def _inputs(**overrides):
    data = dict(
        slides_template_id="slides", doc_template_id="docs",
        target_folder_id="folder", content_title="Unit",
        idempotency_key="key", slides_requests=(), docs_requests=(),
        visual_placements=(), resume_dir="resume",
        placement_transport=None, placement_receipts_dir="placements",
        qa_evidence_dir="qa",
    )
    data.update(overrides)
    return data


def _compose_question_through_production_chain(question: str, **composer_kwargs):
    """Real chain: request builder -> governed composer -> LiveBuildInput."""
    docs_requests = tuple(build_docs_replace_requests(_content(question=question)))
    return compose_governed_build_request(
        **_inputs(docs_requests=docs_requests), **composer_kwargs
    )


@pytest.mark.parametrize("phrase,label", [
    ("heavy modeling", "heavy modeling"),
    ("early stage", "rigor-ramp stage label"),
    ("middle stage", "rigor-ramp stage label"),
    ("late stage", "rigor-ramp stage label"),
    ("teacher model", "teacher modeling script"),
    ("one revision focus", "cognitive-load jargon"),
    ("keeps revision manageable", "cognitive-load jargon"),
    ("cognitive load", "cognitive-load jargon"),
    ("gate rule", "teacher-phrased rule"),
    ("recovery rule", "teacher-phrased rule"),
])
def test_leaked_phrase_in_question_blocks_composition(phrase, label):
    """All ten vocabulary phrases, leaked in a worksheet question, fail closed."""
    with pytest.raises(StudentVoiceError, match=label):
        _compose_question_through_production_chain(
            f"Practice the skill in the {phrase} window before you revise."
        )


def test_leak_in_worksheet_title_blocks_composition():
    docs_requests = tuple(
        build_docs_replace_requests(_content(question="Describe the photo.", title="Early Stage Review"))
    )
    with pytest.raises(StudentVoiceError, match="rigor-ramp stage label"):
        compose_governed_build_request(**_inputs(docs_requests=docs_requests))


def test_leak_in_student_visible_context_token_blocks_composition():
    """Context tokens are student-facing replace text and are screened too."""
    content = _content(question="Describe the photo.").with_context_tokens(
        {"context_tutorial_connection": "Recall our early stage setup day."}
    )
    docs_requests = tuple(build_docs_replace_requests(content))
    with pytest.raises(StudentVoiceError, match="rigor-ramp stage label"):
        compose_governed_build_request(**_inputs(docs_requests=docs_requests))


def test_clean_content_passes_composition_with_text_carried():
    composed = _compose_question_through_production_chain(
        "Describe what changed between the before and after photos."
    )
    replace_texts = [
        request["replaceAllText"]["replaceText"]
        for request in composed.build_input.docs_requests
    ]
    assert any("Describe what changed" in text for text in replace_texts)
    assert composed.build_input.doc_name == "Unit - Worksheet"


def test_explicit_declaration_escape_hatch_preserved():
    composed = _compose_question_through_production_chain(
        "A heavy modeling moment is fine here.",
        explicit_student_copy_teacher_voice_phrases=("heavy modeling",),
    )
    assert composed.build_input.docs_requests


def test_unknown_declaration_fails_closed():
    with pytest.raises(StudentVoiceError, match="unknown student-copy teacher-voice phrase"):
        _compose_question_through_production_chain(
            "A heavy modeling moment is fine here.",
            explicit_student_copy_teacher_voice_phrases=("sentence frames",),
        )


def test_non_replace_requests_carry_no_student_copy():
    composed = compose_governed_build_request(
        **_inputs(docs_requests=({"updateParagraphStyle": {"style": {}}},)),
    )
    assert composed.build_input.docs_requests == ({"updateParagraphStyle": {"style": {}}},)
