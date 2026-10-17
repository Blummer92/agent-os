"""Shared final composition of a governed IMC build request (#3453).

All inputs must already have passed the existing material, curriculum, visual
reuse, worksheet and asset-slot gates. This function grants no authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .artifact_content_qa import TerminalQAExpectations
from .live_build import LiveBuildInput


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
    worksheet_visual_targets: tuple[tuple[str, str], ...] = (),
) -> GovernedBuildRequest:
    """One input/QA/options composition for CLI and scheduled consumers.

    ``worksheet_visual_targets`` carries the lesson-declared required
    worksheet figures as ``(role_id, slot_id)`` pairs (#3212). Each becomes a
    required Docs-scoped visual expectation: a Slides receipt or an
    optional-only binding cannot satisfy it. Empty (no declarations)
    preserves the legacy artifact-agnostic visual expectations unchanged.
    """
    if not all((slides_template_id, doc_template_id, target_folder_id, content_title, idempotency_key)):
        raise ValueError("governed-build-request-identity-missing")
    qa_expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=idempotency_key, docs_requests=docs_requests,
        slides_requests=slides_requests, visual_placements=visual_placements,
        required_docs_visuals=worksheet_visual_targets,
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
