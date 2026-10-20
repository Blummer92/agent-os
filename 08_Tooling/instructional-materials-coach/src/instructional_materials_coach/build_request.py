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


def _planned_tokens(
    requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | None,
) -> set[str]:
    """Collect the bare placeholder tokens covered by replaceAllText requests."""
    planned: set[str] = set()
    for request in tuple(requests or ()):
        replace = request.get("replaceAllText") if isinstance(request, Mapping) else None
        contains = replace.get("containsText") if isinstance(replace, Mapping) else None
        text = contains.get("text") if isinstance(contains, Mapping) else None
        if isinstance(text, str) and text.startswith("{{") and text.endswith("}}") and len(text) > 4:
            planned.add(text[2:-2])
    return planned


def _require_plan_coverage(
    *,
    slides_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | None,
    docs_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | None,
    expected_content_tokens: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    """Fail closed unless every authored token is covered by each plan.

    #3259 D2: the shared composer must never accept a plan that silently
    drops authored content. Terminal-QA expectations are derived per
    artifact from that artifact's plan, so coverage is verified per
    artifact: the demonstrated defect removed ``question_2`` from the Docs
    plan only, and the Docs artifact then verified with zero findings.
    Strict: a caller that cannot state its authored token set fails closed;
    there is no lenient path. Direction is superset per artifact: extra
    requests are allowed, missing expected tokens are not.
    """
    if expected_content_tokens is None or any(
        not isinstance(token, str) or not token for token in expected_content_tokens
    ):
        raise ValueError(
            "build-request-expected-tokens-missing: the caller must supply the "
            "authored content token set; refusing to compose without it"
        )
    expected = tuple(dict.fromkeys(expected_content_tokens))
    problems = []
    for role, requests in (("slides", slides_requests), ("docs", docs_requests)):
        missing = [token for token in expected if token not in _planned_tokens(requests)]
        if missing:
            problems.append(f"{role} plan is missing authored tokens: {', '.join(missing)}")
    if problems:
        raise ValueError(
            "build-request-incomplete-content-plan: " + "; ".join(problems)
        )
    return expected


def compose_governed_build_request(
    *, slides_template_id: str, doc_template_id: str, target_folder_id: str,
    content_title: str, idempotency_key: str,
    slides_requests: tuple[dict[str, Any], ...],
    docs_requests: tuple[dict[str, Any], ...],
    visual_placements: tuple[Any, ...],
    resume_dir: str, placement_transport: object | None,
    placement_receipts_dir: str, qa_evidence_dir: str,
    worksheet_visual_targets: tuple[tuple[str, str], ...] = (),
    expected_content_tokens: tuple[str, ...] | list[str] | None = None,
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
    # #3259 D2: verify authored-content coverage before QA expectations
    # exist and before any external write.
    expected = _require_plan_coverage(
        slides_requests=slides_requests, docs_requests=docs_requests,
        expected_content_tokens=expected_content_tokens,
    )
    qa_expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=idempotency_key, docs_requests=docs_requests,
        slides_requests=slides_requests, visual_placements=visual_placements,
        required_docs_visuals=worksheet_visual_targets,
        expected_content_tokens=expected,
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
    """Host-supplied subject resolver; never synthesize missing governed inputs.

    #3259 D2: the resolver must supply ``expected_content_tokens`` -- the
    authored content-token set -- alongside the planned requests. The shared
    composer fails closed (``build-request-expected-tokens-missing`` /
    ``build-request-incomplete-content-plan``) when the authored set is
    absent or not covered by the plan.
    """
    if not callable(governed_inputs_resolver):
        raise TypeError("governed_inputs_resolver-required")
    inputs = governed_inputs_resolver(request, subject)
    if not isinstance(inputs, Mapping):
        raise ValueError("governed-inputs-unavailable")
    return compose_governed_build_request(**inputs)
