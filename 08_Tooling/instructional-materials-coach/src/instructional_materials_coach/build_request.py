"""Shared final composition of a governed IMC build request (#3453).

All inputs must already have passed the existing material, curriculum, visual
reuse, worksheet and asset-slot gates. This function grants no authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Container, Mapping

from .artifact_content_qa import TerminalQAExpectations
from .live_build import LiveBuildInput
from .student_voice import require_student_voice


@dataclass(frozen=True)
class GovernedBuildRequest:
    build_input: LiveBuildInput
    builder_options: Mapping[str, Any]


def compose_governed_build_request(
    *, slides_template_id: str, doc_template_id: str, target_folder_id: str,
    content_title: str, idempotency_key: str,
    slides_requests: tuple[dict[str, Any], ...],
    docs_requests: tuple[dict[str, Any], ...],
    visual_placements: tuple[Any, ...],
    resume_dir: str, placement_transport: object | None,
    placement_receipts_dir: str, qa_evidence_dir: str,
    # #3644: deliberately student-facing teacher-voice phrases. The
    # student-voice screen fails closed by default; unknown declarations fail
    # closed too (see student_voice.require_student_voice).
    explicit_student_copy_teacher_voice_phrases: tuple[str, ...] = (),
    # #3644 R5: verified projection of the {{token}} names the worksheet Doc
    # template actually carries (e.g. the resolved docs TemplateCandidate's
    # supported_placeholders). Scopes the pre-write voice screen to genuine
    # worksheet copy; a slide-only token the template never uses cannot
    # block the Docs build. None (unverified) scans every replacement
    # value, fail-closed.
    doc_template_tokens: Container[str] | None = None,
) -> GovernedBuildRequest:
    """One input/QA/options composition for CLI and scheduled consumers.

    #3213/#3644: screens the student-facing worksheet replace text for
    teacher-guide modeling voice before any Drive write. A leak raises
    ``StudentVoiceError`` and no ``LiveBuildInput`` is returned, so neither
    the CLI nor a scheduled consumer can proceed with the tainted copy.
    The declared phrases are also carried into the terminal-QA
    expectations so the persisted rendered Doc is rechecked after the
    write with the same exemptions.
    """
    if not all((slides_template_id, doc_template_id, target_folder_id, content_title, idempotency_key)):
        raise ValueError("governed-build-request-identity-missing")
    require_student_voice(
        docs_requests, allowed=explicit_student_copy_teacher_voice_phrases,
        used_tokens=doc_template_tokens,
    )
    qa_expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=idempotency_key, docs_requests=docs_requests,
        slides_requests=slides_requests, visual_placements=visual_placements,
        allowed_teacher_voice_phrases=explicit_student_copy_teacher_voice_phrases,
    )
    return GovernedBuildRequest(
        build_input=LiveBuildInput(
            slides_template_id=slides_template_id, doc_template_id=doc_template_id,
            target_folder_id=target_folder_id, slides_name=f"{content_title} - Slides",
            doc_name=f"{content_title} - Worksheet", idempotency_key=idempotency_key,
            input_fingerprint=idempotency_key, slides_requests=slides_requests,
            docs_requests=docs_requests, visual_placements=visual_placements,
            qa_expectations=qa_expectations,
        ),
        builder_options={
            "resume_dir": resume_dir, "placement_transport": placement_transport,
            "placement_receipts_dir": placement_receipts_dir,
            "qa_evidence_dir": qa_evidence_dir,
        },
    )


def live_build_input_factory(request: object, subject: Mapping[str, Any], *,
                             governed_inputs_resolver: object) -> GovernedBuildRequest:
    """Host-supplied subject resolver; never synthesize missing governed inputs."""
    if not callable(governed_inputs_resolver):
        raise TypeError("governed_inputs_resolver-required")
    inputs = governed_inputs_resolver(request, subject)
    if not isinstance(inputs, Mapping):
        raise ValueError("governed-inputs-unavailable")
    return compose_governed_build_request(**inputs)
