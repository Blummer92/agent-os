"""#3259 D2: incomplete plans fail closed at shared composition.

The shared composer derived terminal-QA expectations exclusively from the
supplied requests, so a truncated plan produced a false VERIFIED.
compose_governed_build_request() now requires the authored token set and
rejects any plan that does not cover it -- per artifact, before QA
expectations exist and before any external write.
"""
import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_CONTENT_MISSING,
    QA_STATE_VERIFIED,
    ArtifactObservation,
    TerminalQAExpectations,
    _try_recover_verified,
    evaluate_artifact_qa,
    persist_qa_report,
    ArtifactQAReport,
    TerminalQAReport,
)
from instructional_materials_coach.artifact_structure import (
    PASS,
    validate_required_worksheet_sections,
)
from instructional_materials_coach.build_receipt import build_receipt_record
from instructional_materials_coach.build_request import (
    compose_governed_build_request,
    live_build_input_factory,
)
from instructional_materials_coach.content_spec import content_from_dict
from instructional_materials_coach.docs_requests import build_docs_replace_requests
from instructional_materials_coach.slides_requests import build_slides_replace_requests


def _lesson():
    return {
        "title": "Fractions",
        "objectives": ["Add fractions"],
        "slides": [
            {"index": 1, "heading": "Welcome", "bullets": ["Hello"]},
            {"index": 2, "heading": "Sums"},
        ],
        "worksheet_questions": ["What is 1/2 + 1/4?", "What is 2/3 - 1/3?"],
    }


def _with_sections(content):
    return content.with_context_tokens(
        {"warm-up": "Warm up: observe the sky.", "exit-ticket": "Exit ticket: one new word."}
    )


def _composed_inputs(docs_requests, slides_requests, expected):
    return dict(
        slides_template_id="slides", doc_template_id="docs",
        target_folder_id="folder", content_title="Fractions",
        idempotency_key="key-3259", slides_requests=tuple(slides_requests),
        docs_requests=tuple(docs_requests), visual_placements=(),
        resume_dir="resume", placement_transport=None,
        placement_receipts_dir="placements", qa_evidence_dir="qa",
        expected_content_tokens=expected,
    )


def _drop(requests, token):
    marker = "{{" + token + "}}"
    return [r for r in requests
            if r["replaceAllText"]["containsText"]["text"] != marker]


def test_truncated_docs_plan_rejected_naming_question_2():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = build_docs_replace_requests(content)
    truncated = _drop(docs_requests, "question_2")
    assert len(truncated) == len(docs_requests) - 1
    with pytest.raises(ValueError, match="build-request-incomplete-content-plan") as exc:
        compose_governed_build_request(**_composed_inputs(
            truncated, build_slides_replace_requests(content), expected))
    assert "question_2" in str(exc.value)
    assert "docs plan" in str(exc.value)


def test_truncated_slides_plan_rejected_naming_slide_token():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    slides_requests = build_slides_replace_requests(content)
    truncated = _drop(slides_requests, "slide_2_heading")
    with pytest.raises(ValueError, match="build-request-incomplete-content-plan") as exc:
        compose_governed_build_request(**_composed_inputs(
            build_docs_replace_requests(content), truncated, expected))
    assert "slide_2_heading" in str(exc.value)
    assert "slides plan" in str(exc.value)


def test_complete_plan_accepted_and_expectations_enumerate_all_tokens():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    composed = compose_governed_build_request(**_composed_inputs(
        build_docs_replace_requests(content),
        build_slides_replace_requests(content), expected))
    qa = composed.build_input.qa_expectations
    assert qa.expected_content_tokens == tuple(sorted(expected))
    planned = {e.token[2:-2] for e in qa.docs_content}
    assert set(expected) <= planned


def test_section_gate_still_rejects_missing_section_tokens():
    # Required-section validation is preserved unchanged.
    content = content_from_dict(_lesson())  # no warm-up / exit-ticket tokens
    result = validate_required_worksheet_sections(
        required_sections=("warm-up", "exit-ticket"),
        curriculum_decision_tokens={"warm-up": "warm-up", "exit-ticket": "exit-ticket"},
        docs_requests=tuple(build_docs_replace_requests(content)),
    )
    assert result.status != PASS


def test_truncated_questions_pass_section_gate_known_limitation():
    # Documents the gate's scope: it checks section tokens, not question
    # counts. The composer coverage check (not the gate) closes this hole.
    content = _with_sections(content_from_dict(_lesson()))
    docs_requests = _drop(build_docs_replace_requests(content), "question_2")
    result = validate_required_worksheet_sections(
        required_sections=("warm-up", "exit-ticket"),
        curriculum_decision_tokens={"warm-up": "warm-up", "exit-ticket": "exit-ticket"},
        docs_requests=tuple(docs_requests),
    )
    assert result.status == PASS


def test_host_path_without_expected_tokens_fails_closed():
    content = _with_sections(content_from_dict(_lesson()))
    docs_requests = _drop(build_docs_replace_requests(content), "question_2")
    inputs = _composed_inputs(docs_requests, build_slides_replace_requests(content),
                              tuple(content.placeholder_tokens()))
    del inputs["expected_content_tokens"]
    with pytest.raises(ValueError, match="build-request-expected-tokens-missing"):
        live_build_input_factory(object(), {}, governed_inputs_resolver=lambda r, s: inputs)


def test_host_path_truncated_plan_with_expected_tokens_rejected():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = _drop(build_docs_replace_requests(content), "question_2")
    inputs = _composed_inputs(docs_requests, build_slides_replace_requests(content), expected)
    with pytest.raises(ValueError, match="build-request-incomplete-content-plan") as exc:
        live_build_input_factory(object(), {}, governed_inputs_resolver=lambda r, s: inputs)
    assert "question_2" in str(exc.value)


def test_host_path_complete_plan_accepted():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    inputs = _composed_inputs(build_docs_replace_requests(content),
                              build_slides_replace_requests(content), expected)
    scheduled = live_build_input_factory(object(), {}, governed_inputs_resolver=lambda r, s: inputs)
    direct = compose_governed_build_request(**inputs)
    assert scheduled == direct


def test_substituted_values_pass_coverage_by_design():
    # Coverage is about presence, not value-correctness: swapping the two
    # questions' texts passes the coverage check. Value-correctness stays
    # in QA's text-proof domain. This test documents the boundary.
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = build_docs_replace_requests(content)
    swapped = []
    for request in docs_requests:
        replace = request["replaceAllText"]
        text = replace["containsText"]["text"]
        if text == "{{question_1}}":
            replace = dict(replace, replaceText="What is 2/3 - 1/3?")
        elif text == "{{question_2}}":
            replace = dict(replace, replaceText="What is 1/2 + 1/4?")
        swapped.append({"replaceAllText": replace})
    composed = compose_governed_build_request(**_composed_inputs(
        swapped, build_slides_replace_requests(content), expected))
    assert composed.build_input.qa_expectations is not None


def test_extra_requests_allowed_superset_direction():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = list(build_docs_replace_requests(content))
    docs_requests.append({"replaceAllText": {"containsText": {"text": "{{host_extra}}"},
                                             "replaceText": "host-added"}})
    composed = compose_governed_build_request(**_composed_inputs(
        docs_requests, build_slides_replace_requests(content), expected))
    assert composed.build_input.qa_expectations is not None


def test_receipt_persists_expected_content_tokens():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    composed = compose_governed_build_request(**_composed_inputs(
        build_docs_replace_requests(content),
        build_slides_replace_requests(content), expected))
    record = build_receipt_record(composed.build_input, None)
    assert record["expected_content_tokens"] == sorted(expected)


def _observation(full_text):
    # artifact_type "docs" is the worksheet's QA identity (run_terminal_qa).
    return ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id="rev-1",
        full_text=full_text,
    )


def _complete_texts(content):
    return [v for k, v in content.placeholder_tokens().items()]


def test_terminal_qa_complete_plan_complete_document_verified():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = build_docs_replace_requests(content)
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key="k", docs_requests=tuple(docs_requests),
        expected_content_tokens=expected)
    report = evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=expectations,
        observation=_observation(" ".join(_complete_texts(content))),
        placement_records=(), idempotency_key="k")
    assert report.state == QA_STATE_VERIFIED
    assert not report.findings


def test_terminal_qa_complete_plan_incomplete_document_fails_closed():
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = build_docs_replace_requests(content)
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key="k", docs_requests=tuple(docs_requests),
        expected_content_tokens=expected)
    incomplete = " ".join(v for k, v in content.placeholder_tokens().items()
                          if k != "question_2")
    report = evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1", expectations=expectations,
        observation=_observation(incomplete),
        placement_records=(), idempotency_key="k")
    assert report.state == QA_STATE_CONTENT_MISSING
    assert any(f.code == "qa-content-missing" for f in report.findings)


def _persisted_verified(tmp_path, expectations, key):
    def _mk(artifact_type, artifact_id):
        return ArtifactQAReport(
            artifact_type=artifact_type, artifact_id=artifact_id, revision_id="rev-1",
            idempotency_key=key, state=QA_STATE_VERIFIED, findings=(),
            expectations_hash=expectations.expectations_hash(), recovered=False)
    report = TerminalQAReport(
        idempotency_key=key, state=QA_STATE_VERIFIED,
        slides=_mk("slides", "slides-1"), worksheet=_mk("worksheet", "doc-1"))
    persist_qa_report(tmp_path, report)


def test_recovery_refuses_truncated_plan_with_authored_tokens(tmp_path):
    # Composer bypassed: expectations built directly from a truncated plan,
    # but the authored token set is bound in. Recovery must refuse.
    content = _with_sections(content_from_dict(_lesson()))
    expected = tuple(content.placeholder_tokens())
    docs_requests = _drop(build_docs_replace_requests(content), "question_2")
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key="k", docs_requests=tuple(docs_requests),
        slides_requests=tuple(build_slides_replace_requests(content)),
        expected_content_tokens=expected)
    _persisted_verified(tmp_path, expectations, "k")
    recovered = _try_recover_verified(
        qa_evidence_dir=str(tmp_path), expectations=expectations,
        artifact_type="worksheet", artifact_id="doc-1",
        observation=_observation("worksheet text"))
    assert recovered is None


def test_recovery_without_authored_tokens_documents_residual_risk(tmp_path):
    # Without the authored set bound in (pre-repair shape), recovery cannot
    # tell a truncated plan from a complete one: it recovers. This test
    # documents the residual risk the second layer exists to remove.
    content = _with_sections(content_from_dict(_lesson()))
    docs_requests = _drop(build_docs_replace_requests(content), "question_2")
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key="k", docs_requests=tuple(docs_requests),
        slides_requests=tuple(build_slides_replace_requests(content)))
    assert expectations.expected_content_tokens == ()
    _persisted_verified(tmp_path, expectations, "k")
    recovered = _try_recover_verified(
        qa_evidence_dir=str(tmp_path), expectations=expectations,
        artifact_type="worksheet", artifact_id="doc-1",
        observation=_observation("worksheet text"))
    assert recovered is not None and recovered.recovered
