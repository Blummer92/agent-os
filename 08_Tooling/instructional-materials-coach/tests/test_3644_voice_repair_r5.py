"""#3644 R5 (#3213): word/token-boundary voice matching + template-scoped screening.

Repair acceptance for the production worksheet voice screen:

- Legitimate "Translate stage directions into a storyboard." and
  "Investigate rules" pass (word boundaries, not substrings).
- Genuine teacher-guide modeling voice still blocks, including hyphen,
  Unicode-dash, zero-width, and split-run variants.
- The pre-write scan covers only the worksheet template's verified used
  tokens; unused slide-only tokens cannot block a Docs build, while the
  same teacher text genuinely rendered in the Doc still fails terminal QA.
- Explicit exemptions stay bounded and are normalized exactly like
  scanned copy.
- Invalid planned copy raises before any LiveBuildInput exists, so no
  Drive write can follow.
"""
from __future__ import annotations

import pytest

from instructional_materials_coach.artifact_content_qa import (
    ArtifactObservation,
    TerminalQAExpectations,
    evaluate_artifact_qa,
)
from instructional_materials_coach.build_request import compose_governed_build_request
from instructional_materials_coach.content_spec import LessonContent
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.slides_requests import build_slides_replace_requests
from instructional_materials_coach.student_voice import (
    StudentVoiceError,
    docs_replace_student_texts,
    normalize_phrase,
    require_student_voice,
    scan_teacher_voice,
)

KEY = "k" * 64
# Verified worksheet-template projection: the template carries the title,
# objective, and question tokens -- never the slide tokens.
DOC_TEMPLATE_TOKENS = ("title", "objective_1", "question_1")


def _content(*, question="Describe the scene.", heading="Observe"):
    return LessonContent(
        title="Lesson",
        objectives=["Compare"],
        slides=[{"index": 1, "heading": heading, "bullets": []}],
        worksheet_questions=[question],
    )


def _inputs(**overrides):
    data = dict(
        slides_template_id="slides", doc_template_id="docs",
        target_folder_id="folder", content_title="Unit",
        idempotency_key=KEY, slides_requests=(), docs_requests=(),
        visual_placements=(), resume_dir="resume",
        placement_transport=None, placement_receipts_dir="placements",
        qa_evidence_dir="qa",
    )
    data.update(overrides)
    return data


def _compose(content, **composer_kwargs):
    docs_requests = tuple(build_docs_replace_requests(content))
    return compose_governed_build_request(
        **_inputs(
            docs_requests=docs_requests,
            slides_requests=tuple(build_slides_replace_requests(content)),
            # #3259 D2 (current main): the composer fails closed unless the
            # caller supplies the authored token set, as cli.py does.
            expected_content_tokens=tuple(content.placeholder_tokens()),
        ),
        **composer_kwargs,
    )


# ---------------------------------------------------------------------------
# Word/token boundaries: the two reported false positives now pass.
# ---------------------------------------------------------------------------

def test_translate_stage_directions_passes():
    assert scan_teacher_voice(("Translate stage directions into a storyboard.",)) == ()


def test_investigate_rules_passes():
    assert scan_teacher_voice(("Investigate rules for the gallery walk.",)) == ()


def test_translate_stage_passes_end_to_end_through_composer():
    composed = _compose(_content(question="Translate stage directions into a storyboard."))
    assert composed.build_input.docs_requests


def test_investigate_rules_passes_end_to_end_through_composer():
    composed = _compose(_content(question="Investigate rules for the gallery walk."))
    assert composed.build_input.docs_requests


@pytest.mark.parametrize("text", [
    "the late stage review",          # word-boundary hit, not "translate"
    "follow the gate rule exactly",   # word-boundary hit, not "investigate"
    "cognitiveload is fine",          # no boundary, no hit
    "translate-stage directions",     # dash splits words; "late stage" still not a word hit
])
def test_boundary_semantics(text):
    found = scan_teacher_voice((text,))
    assert ("rigor-ramp stage label" in found) == ("late stage review" in text)
    assert ("teacher-phrased rule" in found) == ("gate rule exactly" in text)


def test_plural_gate_rules_is_outside_the_bounded_vocabulary():
    # Word boundaries are what let "Investigate rules" pass; the bounded
    # vocabulary therefore does not reach the plural "gate rules".
    assert scan_teacher_voice(("Follow the gate rules for critique.",)) == ()


# ---------------------------------------------------------------------------
# Genuine teacher voice still blocks, including evasions.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "heavy modeling", "early stage", "middle stage", "late stage",
    "teacher model", "one revision focus", "keeps revision manageable",
    "cognitive load", "gate rule", "recovery rule",
])
def test_every_vocabulary_phrase_still_blocks(phrase):
    found = scan_teacher_voice((f"Practice in the {phrase} window before you revise.",))
    assert found, phrase


def test_hyphen_evasion_blocked():
    found = scan_teacher_voice(
        ("Heavy-modeling follows the early-stage teacher-model script.",))
    assert "heavy modeling" in found
    assert "rigor-ramp stage label" in found
    assert "teacher modeling script" in found


@pytest.mark.parametrize("text,label", [
    ("Late\u2014stage review before export.", "rigor-ramp stage label"),   # em dash
    ("Late\u2013stage review before export.", "rigor-ramp stage label"),   # en dash
    ("Follow the teacher\u2011model script.", "teacher modeling script"),  # non-breaking hyphen
    ("One\u00adrevis\u00adion focus for today.", "cognitive-load jargon"),  # soft hyphens
    ("One revision\u00adfocus for today.", "cognitive-load jargon"),  # soft hyphen between words
])
def test_unicode_dash_variants_blocked(text, label):
    assert label in scan_teacher_voice((text,))


@pytest.mark.parametrize("text,label", [
    ("Heavy\u200bmodeling is our routine.", "heavy modeling"),        # zero-width space, no gap
    ("Heavy\u200b modeling is our routine.", "heavy modeling"),        # zero-width space + gap
    ("Use the teacher\u200c model.", "teacher modeling script"),       # zero-width non-joiner
    ("Use the teacher\u200d model.", "teacher modeling script"),       # zero-width joiner
    ("\ufeffGate rule: ask before moving on.", "teacher-phrased rule"),  # BOM
])
def test_zero_width_variants_blocked(text, label):
    assert label in scan_teacher_voice((text,))


@pytest.mark.parametrize("text,label", [
    ("Follow the teacher\nmodel script.", "teacher modeling script"),  # split run
    ("Early \n stage work today.", "rigor-ramp stage label"),          # split run
    ("Heavy-\nmodeling carries the thinking.", "heavy modeling"),       # hyphenated line split
])
def test_split_run_variants_blocked(text, label):
    assert label in scan_teacher_voice((text,))


def test_normalize_phrase_handles_separators_and_case():
    assert normalize_phrase("Heavy\u2014\u200bmodeling") == "heavy modeling"
    assert normalize_phrase("  Gate\nRULE ") == "gate rule"


# ---------------------------------------------------------------------------
# Template-token scoping: unused slide-only tokens do not block Docs.
# ---------------------------------------------------------------------------

def _slide_only_teacher_content():
    return _content(question="Describe the scene.", heading="heavy modeling")


def test_unused_slide_only_tokens_do_not_block_docs_build():
    composed = _compose(
        _slide_only_teacher_content(), doc_template_tokens=DOC_TEMPLATE_TOKENS
    )
    assert composed.build_input.docs_requests


def test_braced_projection_tokens_are_accepted():
    composed = _compose(
        _slide_only_teacher_content(),
        doc_template_tokens=("{{title}}", "{{objective_1}}", "{{question_1}}"),
    )
    assert composed.build_input.docs_requests


def test_slide_token_genuinely_in_template_stays_in_scope():
    # No hard-coded slide_* skip: when the worksheet template really
    # carries the slide token, its text is screened.
    with pytest.raises(StudentVoiceError, match="heavy modeling"):
        _compose(
            _slide_only_teacher_content(),
            doc_template_tokens=DOC_TEMPLATE_TOKENS + ("slide_1_heading",),
        )


def test_unverified_projection_scans_everything_fail_closed():
    with pytest.raises(StudentVoiceError, match="heavy modeling"):
        _compose(_slide_only_teacher_content())


def test_unparseable_token_stays_in_scope_fail_closed():
    requests = (
        {"replaceAllText": {"replaceText": "heavy modeling everywhere"}},
    )
    with pytest.raises(StudentVoiceError, match="heavy modeling"):
        require_student_voice(requests, used_tokens=DOC_TEMPLATE_TOKENS)


def test_docs_replace_student_texts_scoping():
    requests = tuple(build_docs_replace_requests(_slide_only_teacher_content()))
    scoped = docs_replace_student_texts(requests, used_tokens=DOC_TEMPLATE_TOKENS)
    assert not any("heavy modeling" in text for text in scoped)
    assert any("Describe the scene." in text for text in scoped)
    unscoped = docs_replace_student_texts(requests)
    assert any("heavy modeling" in text for text in unscoped)


def test_genuine_worksheet_teacher_voice_still_blocks_with_projection():
    with pytest.raises(StudentVoiceError, match="rigor-ramp stage label"):
        _compose(
            _content(question="Follow the late stage gate rule before you revise."),
            doc_template_tokens=DOC_TEMPLATE_TOKENS,
        )


# ---------------------------------------------------------------------------
# Bounded exemptions, normalized exactly like scanned copy.
# ---------------------------------------------------------------------------

def test_exemption_with_zero_width_variant_still_validates():
    found = scan_teacher_voice(
        ("Heavy\u200bmodeling helps here.",), allowed=("heavy\u200bmodeling",)
    )
    assert found == ()


def test_exemption_typo_with_zero_width_still_fails_closed():
    with pytest.raises(StudentVoiceError, match="unknown student-copy teacher-voice phrase"):
        require_student_voice(
            tuple(build_docs_replace_requests(_content(question="Heavy modeling helps."))),
            allowed=("hevy\u200bmodeling",),
        )


def test_duplicate_declarations_normalized_before_uniqueness():
    with pytest.raises(StudentVoiceError, match="must be unique"):
        require_student_voice((), allowed=("Gate Rule", "gate\u200brule"))


def test_declaration_bound_still_enforced():
    with pytest.raises(StudentVoiceError, match="bounded build limit"):
        require_student_voice((), allowed=tuple(["heavy modeling"] * 17))


def test_explicit_declaration_escape_hatch_preserved_with_projection():
    composed = _compose(
        _content(question="A heavy modeling moment is fine here."),
        doc_template_tokens=DOC_TEMPLATE_TOKENS,
        explicit_student_copy_teacher_voice_phrases=("heavy modeling",),
    )
    assert composed.build_input.docs_requests


# ---------------------------------------------------------------------------
# Zero Drive writes when planned copy is already invalid.
# ---------------------------------------------------------------------------

def test_invalid_planned_copy_raises_before_any_build_input_exists():
    content = _content(question="Follow the late stage gate rule before you revise.")
    docs_requests = tuple(build_docs_replace_requests(content))
    with pytest.raises(StudentVoiceError, match="teacher-phrased rule"):
        compose_governed_build_request(**_inputs(
            docs_requests=docs_requests,
            slides_requests=tuple(build_slides_replace_requests(content)),
            expected_content_tokens=tuple(content.placeholder_tokens()),
        ))
    # No GovernedBuildInput/LiveBuildInput is returned: neither the CLI nor
    # a scheduled consumer can proceed to a Drive write with tainted copy.


# ---------------------------------------------------------------------------
# Persisted rendered Docs text is rechecked after the write.
# ---------------------------------------------------------------------------

def _persisted_qa(*, persisted_text, docs_requests, allowed=()):
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY,
        docs_requests=docs_requests,
        allowed_teacher_voice_phrases=allowed,
    )
    observation = ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1",
        revision_id="rev-1", full_text=persisted_text,
    )
    report = evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1",
        expectations=expectations, observation=observation,
        placement_records=(), idempotency_key=KEY,
    )
    return report


def _clean_docs_requests():
    return tuple(build_docs_replace_requests(_content(question="Describe the scene.")))


def test_same_teacher_text_genuinely_in_doc_blocks_terminal_qa():
    # Slide-only teacher text scoped out of the pre-write scan must still
    # fail when it is actually rendered in the worksheet Doc (e.g. via
    # inherited template boilerplate the composer never sees).
    report = _persisted_qa(
        persisted_text="Lesson\nDescribe the scene.\nheavy modeling carries the thinking.",
        docs_requests=_clean_docs_requests(),
    )
    codes = [finding.code for finding in report.findings]
    assert "qa-teacher-voice-in-worksheet" in codes
    assert report.state != "verified"


def test_persisted_clean_doc_has_no_voice_finding():
    report = _persisted_qa(
        persisted_text="Lesson\nDescribe the scene.\nTranslate stage directions into a storyboard.",
        docs_requests=_clean_docs_requests(),
    )
    assert "qa-teacher-voice-in-worksheet" not in [
        finding.code for finding in report.findings
    ]


def test_persisted_voice_exemption_honored():
    report = _persisted_qa(
        persisted_text="Lesson\nThe late stage review is student-facing by design.",
        docs_requests=_clean_docs_requests(),
        allowed=("late stage",),
    )
    assert "qa-teacher-voice-in-worksheet" not in [
        finding.code for finding in report.findings
    ]


def test_persisted_voice_evasion_variants_caught():
    report = _persisted_qa(
        persisted_text="Lesson\nHeavy\u200bmodeling and the early\u2014stage script.",
        docs_requests=_clean_docs_requests(),
    )
    codes = [finding.code for finding in report.findings]
    assert "qa-teacher-voice-in-worksheet" in codes
    labels = next(
        finding for finding in report.findings
        if finding.code == "qa-teacher-voice-in-worksheet"
    ).detail["labels"]
    assert "heavy modeling" in labels
    assert "rigor-ramp stage label" in labels


def test_persisted_voice_check_is_docs_only():
    expectations = TerminalQAExpectations.build_from_requests(idempotency_key=KEY)
    observation = ArtifactObservation(
        artifact_type="slides", artifact_id="slides-1",
        revision_id="rev-1", full_text="heavy modeling carries the thinking",
    )
    report = evaluate_artifact_qa(
        artifact_type="slides", artifact_id="slides-1",
        expectations=expectations, observation=observation,
        placement_records=(), idempotency_key=KEY,
    )
    assert "qa-teacher-voice-in-worksheet" not in [
        finding.code for finding in report.findings
    ]


def test_expectations_hash_binds_voice_declarations():
    plain = TerminalQAExpectations.build_from_requests(idempotency_key=KEY)
    declared = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, allowed_teacher_voice_phrases=("heavy modeling",)
    )
    assert declared.allowed_teacher_voice_phrases == ("heavy modeling",)
    assert plain.expectations_hash() != declared.expectations_hash()
