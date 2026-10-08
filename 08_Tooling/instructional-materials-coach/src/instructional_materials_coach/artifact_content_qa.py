"""Terminal artifact-content QA (#3258).

Proves that the PERSISTED final artifact contains the governed required
content and governed required visuals, attributable to the current build
and artifact state.

Agent OS must not declare a build complete solely because generation
succeeded, text replacement succeeded, visual placement succeeded, a
placement receipt exists, a Google Doc/Slides artifact exists, an export
succeeded, or repository tests are green. Terminal success requires
evidence read back from the persisted artifact itself:

- artifact identity (correct Docs/Slides file),
- artifact revision/content identity (evidence bound to the current state),
- required text present and correct (no unresolved ``{{tokens}}``),
- required visuals present, matching the governed selected assets and
  verified placement receipts, at their expected targets,
- no stale, conflicting, or incomplete evidence,
- attribution to the same governed build / idempotency identity.

Upstream ownership is unchanged: visual selection (#944/visual_reuse),
asset provenance (reusable_visual_identity, asset_content_identity #3256),
placement (connected_visual_placement #3257), and receipt creation /
verification (placement_receipts, verify_placement_receipt #2087) are
consumed here, never reimplemented. The existing
``worksheet_revision_qa.validate_revision_render_visuals`` /
``visual_completeness`` contracts are wired into the visual dimension so
no parallel QA framework is created.

Fail-closed throughout: missing, stale, conflicting, or inaccessible
evidence never admits terminal success.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .placement_receipts import load_placement_records
from .worksheet_pagination import HeadingParagraph, headings_missing_keep_with_next
from .worksheet_revision_qa import validate_revision_render_visuals


TERMINAL_QA_CONTRACT = "terminal-artifact-content-qa-v1"
# v2 (#3416): verified evidence now includes the heading keep-with-next
# rule; v1 evidence predates it and is never recovered as verified.
QA_EVIDENCE_CONTRACT = "terminal-qa-evidence-v2"

# Default directory for durable terminal-QA evidence (mirrors the
# placement-receipts default; the CLI overrides it with --qa-evidence-dir).
DEFAULT_QA_EVIDENCE_DIR = "reports/terminal-qa"

# Required QA result states (#3258 contract). ``not-run`` is the initial
# value carried on receipts before QA executes.
QA_STATE_VERIFIED = "verified"
QA_STATE_TOKEN_UNRESOLVED = "token-unresolved"
QA_STATE_CONTENT_MISSING = "content-missing"
QA_STATE_CONTENT_MISMATCH = "content-mismatch"
QA_STATE_VISUAL_MISSING = "visual-missing"
QA_STATE_VISUAL_MISMATCH = "visual-mismatch"
# #3416: a worksheet heading lacks effective keepWithNext, so it can be
# stranded at the foot of a page away from the content it introduces.
QA_STATE_LAYOUT_RULE_VIOLATED = "layout-rule-violated"
QA_STATE_PLACEMENT_UNVERIFIED = "placement-unverified"
QA_STATE_ARTIFACT_STALE = "artifact-stale"
QA_STATE_ARTIFACT_INACCESSIBLE = "artifact-inaccessible"
QA_STATE_ARTIFACT_CONFLICT = "artifact-conflict"
QA_STATE_EVIDENCE_INCOMPLETE = "evidence-incomplete"
QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE = "verification-runtime-unavailable"
QA_STATE_NOT_RUN = "not-run"

# Worst-state precedence for aggregating findings into one artifact state.
# Anything other than ``verified`` refuses terminal completion. Visual
# proof failures (11) outrank the generic token/content states (10): the
# visual dimension carries role/slot/receipt attribution, the more
# actionable diagnosis, while the token-level finding is still recorded
# per the #3258 acceptance criterion.
_STATE_SEVERITY = {
    QA_STATE_VERIFIED: 0,
    QA_STATE_TOKEN_UNRESOLVED: 10,
    QA_STATE_CONTENT_MISSING: 10,
    QA_STATE_CONTENT_MISMATCH: 10,
    QA_STATE_LAYOUT_RULE_VIOLATED: 10,
    QA_STATE_VISUAL_MISSING: 11,
    QA_STATE_VISUAL_MISMATCH: 11,
    QA_STATE_PLACEMENT_UNVERIFIED: 11,
    QA_STATE_ARTIFACT_STALE: 20,
    QA_STATE_ARTIFACT_CONFLICT: 20,
    QA_STATE_EVIDENCE_INCOMPLETE: 30,
    QA_STATE_ARTIFACT_INACCESSIBLE: 40,
    QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE: 40,
    QA_STATE_NOT_RUN: 50,
}

# Unresolved template tokens: {{...}} markers that must never survive into
# a final artifact. Newlines are excluded so multi-line prose is not
# misread as a token.
_TOKEN_RE = re.compile(r"\{\{[^{}\n]*\}\}")

# Cap on token findings listed per artifact; the count is always exact.
_MAX_TOKEN_FINDINGS = 10


class ArtifactInaccessibleError(RuntimeError):
    """The persisted artifact could not be read back."""


class VerificationRuntimeUnavailableError(RuntimeError):
    """No artifact-readback capability exists for this run.

    Distinct from inaccessibility: the runtime itself (injected service)
    cannot perform persisted-artifact reads, so QA cannot even attempt
    verification. Terminal admission must treat this as blocked/nonterminal,
    never success.
    """


def normalize_text(text: str) -> str:
    """Whitespace-fold comparison text.

    Collapses every whitespace run to a single space and strips the ends.
    This is the ONLY normalization applied: it never permits materially
    incorrect content (no case folding, no punctuation stripping, no fuzzy
    matching). ``matchCase=True`` semantics from the write requests are
    preserved.
    """
    return " ".join(str(text).split())


def scan_unresolved_tokens(text: str) -> tuple[str, ...]:
    """Return every unresolved ``{{token}}`` marker present in observed text."""
    return tuple(sorted(set(_TOKEN_RE.findall(text or ""))))


@dataclass(frozen=True)
class ContentExpectation:
    """One governed required-content expectation for one artifact."""

    artifact_type: str  # "docs" | "slides"
    token: str  # e.g. "{{title}}"; must be absent from the final artifact
    expected_text: str  # governed correct text; must be present
    location_hint: Mapping[str, Any] | None = None  # e.g. {"slide_index": 2}
    max_occurrences: int | None = None  # when set, more occurrences => mismatch


@dataclass(frozen=True)
class VisualExpectation:
    """One governed required/optional visual expectation (Wave 3 binding)."""

    role_id: str
    slot_id: str
    asset_id: str
    content_identity: Mapping[str, Any]
    required: bool = True

    def marker(self) -> str:
        return "{{visual:" + self.role_id + "}}"


@dataclass(frozen=True)
class TerminalQAExpectations:
    """The governed expectations terminal QA evaluates the artifact against."""

    idempotency_key: str
    docs_content: tuple[ContentExpectation, ...] = ()
    slides_content: tuple[ContentExpectation, ...] = ()
    visuals: tuple[VisualExpectation, ...] = ()

    @staticmethod
    def build_from_requests(
        *,
        idempotency_key: str,
        docs_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        slides_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        visual_placements: tuple[Any, ...] = (),
    ) -> "TerminalQAExpectations":
        """Derive expectations from the governed planned build inputs.

        Content expectations come from the planned ``replaceAllText``
        requests: the ``containsText`` token must be gone from the persisted
        artifact and the ``replaceText`` must be present. Visual expectations
        come from the Wave 3 placement bindings (role/slot/asset/exact
        content identity). Nothing is inferred beyond these governed inputs.
        """
        return TerminalQAExpectations(
            idempotency_key=str(idempotency_key or ""),
            docs_content=tuple(
                expectation
                for expectation in (
                    _expectation_from_request("docs", request) for request in docs_requests or ()
                )
                if expectation is not None
            ),
            slides_content=tuple(
                expectation
                for expectation in (
                    _expectation_from_request("slides", request) for request in slides_requests or ()
                )
                if expectation is not None
            ),
            visuals=tuple(
                VisualExpectation(
                    role_id=str(binding.role_id),
                    slot_id=str(binding.slot_id),
                    asset_id=str(binding.asset_id),
                    content_identity=dict(binding.content_identity or {}),
                    required=bool(binding.required),
                )
                for binding in visual_placements or ()
            ),
        )

    def expectations_hash(self) -> str:
        payload = {
            "docs": [
                {"token": e.token, "text": e.expected_text,
                 "location": dict(e.location_hint or {}),
                 "max_occurrences": e.max_occurrences}
                for e in self.docs_content
            ],
            "slides": [
                {"token": e.token, "text": e.expected_text,
                 "location": dict(e.location_hint or {}),
                 "max_occurrences": e.max_occurrences}
                for e in self.slides_content
            ],
            "visuals": [
                {"role_id": v.role_id, "slot_id": v.slot_id, "asset_id": v.asset_id,
                 "content_identity": dict(v.content_identity), "required": v.required}
                for v in self.visuals
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def for_artifact(self, artifact_type: str) -> tuple[ContentExpectation, ...]:
        if artifact_type == "docs":
            return self.docs_content
        return self.slides_content


def _expectation_from_request(artifact_type: str, request: Mapping[str, Any]) -> ContentExpectation | None:
    try:
        replace = request.get("replaceAllText") if isinstance(request, Mapping) else None
        contains = replace.get("containsText") if isinstance(replace, Mapping) else None
        token = contains.get("text") if isinstance(contains, Mapping) else None
        expected = replace.get("replaceText") if isinstance(replace, Mapping) else None
    except AttributeError:
        return None
    if not isinstance(token, str) or not token:
        return None
    if isinstance(expected, dict):
        # Test-fake shape: {"text": ...}; production requests carry a plain
        # string. Both are governed replacement text.
        expected = expected.get("text")
    if not isinstance(expected, str):
        return None
    return ContentExpectation(artifact_type=artifact_type, token=token, expected_text=expected)


@dataclass(frozen=True)
class ArtifactObservation:
    """Structured readback of the persisted artifact at QA time."""

    artifact_type: str
    artifact_id: str
    revision_id: str
    full_text: str
    token_hits: tuple[str, ...] = ()
    image_element_ids: tuple[str, ...] = ()
    slide_texts: tuple[str, ...] = ()  # per-slide normalized text; () for docs
    # #3416: docs heading paragraphs lacking effective keepWithNext; () for slides
    headings_without_keep_with_next: tuple[HeadingParagraph, ...] = ()
    observed_at: str = ""


@dataclass(frozen=True)
class QAFinding:
    code: str
    severity: str  # "fail" | "advisory"
    state: str  # the QA state this finding contributes
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactQAReport:
    artifact_type: str
    artifact_id: str
    revision_id: str
    idempotency_key: str
    state: str
    findings: tuple[QAFinding, ...] = ()
    expectations_hash: str = ""
    recovered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": TERMINAL_QA_CONTRACT,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "revision_id": self.revision_id,
            "idempotency_key": self.idempotency_key,
            "state": self.state,
            "expectations_hash": self.expectations_hash,
            "recovered": self.recovered,
            "findings": [
                {"code": f.code, "severity": f.severity, "state": f.state,
                 "message": f.message, "detail": dict(f.detail)}
                for f in self.findings
            ],
        }


@dataclass(frozen=True)
class TerminalQAReport:
    idempotency_key: str
    slides: ArtifactQAReport
    worksheet: ArtifactQAReport
    state: str
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": TERMINAL_QA_CONTRACT,
            "idempotency_key": self.idempotency_key,
            "state": self.state,
            "generated_at": self.generated_at,
            "slides": self.slides.to_dict(),
            "worksheet": self.worksheet.to_dict(),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Persisted-artifact observation (read-only)
# ---------------------------------------------------------------------------

def _read_resource(service: Any, artifact_type: str, artifact_id: str) -> dict[str, Any]:
    """Read the full persisted resource; fail closed on any read problem."""
    resource_fn_name = "documents" if artifact_type == "docs" else "presentations"
    accessor = getattr(service, resource_fn_name, None)
    if accessor is None or not callable(accessor):
        raise VerificationRuntimeUnavailableError(
            "verification-runtime-unavailable: the injected "
            f"{artifact_type} service exposes no {resource_fn_name}() read surface"
        )
    resource_fn = accessor()
    read = getattr(resource_fn, "get", None)
    if read is None or not callable(read):
        raise VerificationRuntimeUnavailableError(
            "verification-runtime-unavailable: the injected "
            f"{artifact_type} resource exposes no get() read operation"
        )
    try:
        if artifact_type == "docs":
            resource = read(documentId=artifact_id).execute()
        else:
            resource = read(presentationId=artifact_id).execute()
    except (VerificationRuntimeUnavailableError, ArtifactInaccessibleError):
        raise
    except Exception as exc:
        raise ArtifactInaccessibleError(
            f"artifact-inaccessible: persisted {artifact_type} artifact "
            f"{artifact_id} could not be read back: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(resource, dict):
        raise ArtifactInaccessibleError(
            f"artifact-inaccessible: persisted {artifact_type} artifact "
            f"{artifact_id} readback did not return a resource mapping"
        )
    return resource


def _docs_text_and_images(document: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Extract Docs body text and inline-object (image) element ids."""
    parts: list[str] = []
    image_ids: list[str] = []

    def _walk_content(content: Any) -> None:
        if not isinstance(content, list):
            return
        for element in content:
            if not isinstance(element, dict):
                continue
            paragraph = element.get("paragraph")
            if isinstance(paragraph, dict):
                for child in paragraph.get("elements", []):
                    if not isinstance(child, dict):
                        continue
                    text_run = child.get("textRun")
                    if isinstance(text_run, dict):
                        parts.append(str(text_run.get("content", "")))
                    inline = child.get("inlineObjectElement")
                    if isinstance(inline, dict) and inline.get("embeddedObjectId"):
                        image_ids.append(str(inline["embeddedObjectId"]))
            table = element.get("table")
            if isinstance(table, dict):
                for row in table.get("tableRows", []):
                    if not isinstance(row, dict):
                        continue
                    for cell in row.get("tableCells", []):
                        if isinstance(cell, dict):
                            _walk_content(cell.get("content"))

    _walk_content((document.get("body") or {}).get("content"))
    inline_objects = document.get("inlineObjects") or {}
    if isinstance(inline_objects, dict):
        for object_id in inline_objects:
            if str(object_id) not in image_ids:
                image_ids.append(str(object_id))
    return "".join(parts), image_ids


def _slides_text_and_images(presentation: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Extract per-slide text and every page-element object id (images incl.)."""
    slide_texts: list[str] = []
    element_ids: list[str] = []
    slides = presentation.get("slides")
    if not isinstance(slides, list):
        return [], []
    for slide in slides:
        if not isinstance(slide, dict):
            slide_texts.append("")
            continue
        parts: list[str] = []
        for element in slide.get("pageElements", []):
            if not isinstance(element, dict):
                continue
            object_id = element.get("objectId")
            if object_id:
                element_ids.append(str(object_id))
            shape = element.get("shape")
            if isinstance(shape, dict):
                text = shape.get("text")
                if isinstance(text, dict):
                    for text_element in text.get("textElements", []):
                        if not isinstance(text_element, dict):
                            continue
                        text_run = text_element.get("textRun")
                        if isinstance(text_run, dict):
                            parts.append(str(text_run.get("content", "")))
        slide_texts.append(normalize_text("".join(parts)))
    return slide_texts, element_ids


def observe_artifact(service: Any, artifact_type: str, artifact_id: str) -> ArtifactObservation:
    """Read back the persisted artifact and structure it for QA.

    Raises ``VerificationRuntimeUnavailableError`` when the injected
    service has no read surface, ``ArtifactInaccessibleError`` when the
    read fails or returns an unusable resource.
    """
    resource = _read_resource(service, artifact_type, artifact_id)
    revision_id = resource.get("revisionId")
    if not isinstance(revision_id, str) or not revision_id:
        raise ArtifactInaccessibleError(
            f"artifact-inaccessible: persisted {artifact_type} artifact "
            f"{artifact_id} readback carries no revisionId; QA evidence "
            "cannot be bound to an artifact state"
        )
    # Identity check when the resource echoes its own id (defensive: we
    # read by id, but a misbehaving service must not silently substitute).
    echoed = resource.get("documentId") if artifact_type == "docs" else resource.get("presentationId")
    if isinstance(echoed, str) and echoed and echoed != artifact_id:
        raise ArtifactInaccessibleError(
            f"artifact-conflict: readback for {artifact_id} returned a "
            f"different {artifact_type} artifact {echoed}"
        )
    headings: tuple[HeadingParagraph, ...] = ()
    if artifact_type == "docs":
        full_text, image_ids = _docs_text_and_images(resource)
        slide_texts: tuple[str, ...] = ()
        headings = headings_missing_keep_with_next(resource)
    else:
        slide_texts_list, image_ids = _slides_text_and_images(resource)
        slide_texts = tuple(slide_texts_list)
        full_text = "\n".join(slide_texts_list)
    return ArtifactObservation(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        revision_id=revision_id,
        full_text=full_text,
        token_hits=scan_unresolved_tokens(full_text),
        image_element_ids=tuple(image_ids),
        slide_texts=slide_texts,
        headings_without_keep_with_next=headings,
        observed_at=_utc_now(),
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _fail(code: str, state: str, message: str, **detail: Any) -> QAFinding:
    return QAFinding(code=code, severity="fail", state=state, message=message, detail=detail)


def _advisory(code: str, state: str, message: str, **detail: Any) -> QAFinding:
    return QAFinding(code=code, severity="advisory", state=state, message=message, detail=detail)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _evaluate_content(
    *,
    artifact_type: str,
    observation: ArtifactObservation,
    expectations: tuple[ContentExpectation, ...],
) -> list[QAFinding]:
    findings: list[QAFinding] = []
    normalized_full = normalize_text(observation.full_text)
    for expectation in expectations:
        norm_expected = normalize_text(expectation.expected_text)
        if not norm_expected:
            continue  # vacuous expectation: nothing governed to prove
        scope_text = observation.full_text
        normalized_scope = normalized_full
        hint = expectation.location_hint or {}
        slide_index = hint.get("slide_index")
        if slide_index is not None:
            if artifact_type != "slides" or not isinstance(slide_index, int) or not (
                0 <= slide_index < len(observation.slide_texts)
            ):
                findings.append(
                    _fail(
                        "qa-location-hint-invalid", QA_STATE_EVIDENCE_INCOMPLETE,
                        f"Content expectation for token {expectation.token} carries an "
                        f"unevaluable location hint {dict(hint)}; QA cannot prove "
                        "structural location.",
                        token=expectation.token, location_hint=dict(hint),
                    )
                )
                continue
            scope_text = observation.slide_texts[slide_index]
            # slide_texts are already normalized
            normalized_scope = scope_text
        if expectation.token in scope_text:
            findings.append(
                _fail(
                    "qa-token-unresolved", QA_STATE_TOKEN_UNRESOLVED,
                    f"Unresolved template token {expectation.token} persists in the "
                    f"{artifact_type} artifact; the write did not fully apply.",
                    token=expectation.token,
                )
            )
            continue
        if norm_expected not in normalized_scope:
            findings.append(
                _fail(
                    "qa-content-missing", QA_STATE_CONTENT_MISSING,
                    f"Required content for token {expectation.token} is absent from "
                    f"the persisted {artifact_type} artifact.",
                    token=expectation.token,
                )
            )
            continue
        if expectation.max_occurrences is not None:
            occurrences = normalized_scope.count(norm_expected)
            if occurrences > expectation.max_occurrences:
                findings.append(
                    _fail(
                        "qa-content-duplicated", QA_STATE_CONTENT_MISMATCH,
                        f"Required content for token {expectation.token} appears "
                        f"{occurrences} times in the persisted {artifact_type} "
                        f"artifact (max {expectation.max_occurrences}); invalid "
                        "duplication.",
                        token=expectation.token, occurrences=occurrences,
                        max_occurrences=expectation.max_occurrences,
                    )
                )
    return findings


def _evaluate_visuals(
    *,
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
    visual_expectations: tuple[VisualExpectation, ...],
    placement_records: tuple[dict[str, Any], ...],
) -> list[QAFinding]:
    findings: list[QAFinding] = []
    verified_roles: list[str] = []
    unresolved_roles: list[str] = []
    required_roles_here: list[str] = []

    for visual in visual_expectations:
        records_here = [
            record for record in placement_records
            if record.get("state") == "verified"
            and record.get("role_id") == visual.role_id
            and str(record.get("slot_id")) == str(visual.slot_id)
            and record.get("artifact_type") == artifact_type
        ]
        records_anywhere = [
            record for record in placement_records
            if record.get("state") == "verified"
            and record.get("role_id") == visual.role_id
            and str(record.get("slot_id")) == str(visual.slot_id)
        ]
        if not records_anywhere:
            if visual.required:
                # A required visual was never verified-placed in any artifact:
                # terminal QA cannot admit the build. Named explicitly so the
                # unresolved roles can be routed to manual review.
                unresolved_roles.append(visual.role_id)
                findings.append(
                    _fail(
                        "qa-placement-unverified", QA_STATE_PLACEMENT_UNVERIFIED,
                        f"Required visual role {visual.role_id} (slot {visual.slot_id}) "
                        f"has no verified placement receipt in any artifact; the "
                        "build cannot be terminal.",
                        role_id=visual.role_id, slot_id=visual.slot_id,
                    )
                )
            continue
        if not records_here:
            # Placed in another artifact (marker routing); not expected here.
            continue
        if visual.required:
            required_roles_here.append(visual.role_id)
        if len(records_here) > 1:
            findings.append(
                _fail(
                    "qa-receipt-conflict", QA_STATE_ARTIFACT_CONFLICT,
                    f"Multiple verified placement receipts for role {visual.role_id} "
                    f"slot {visual.slot_id} in {artifact_type} {artifact_id}; "
                    "conflicting evidence.",
                    role_id=visual.role_id, slot_id=visual.slot_id,
                    receipt_count=len(records_here),
                )
            )
            continue
        record = records_here[0]
        if str(record.get("artifact_id")) != artifact_id:
            findings.append(
                _fail(
                    "qa-receipt-artifact-conflict", QA_STATE_ARTIFACT_CONFLICT,
                    f"Placement receipt for role {visual.role_id} references artifact "
                    f"{record.get('artifact_id')}, not the inspected {artifact_id}.",
                    role_id=visual.role_id,
                    receipt_artifact_id=str(record.get("artifact_id")),
                    inspected_artifact_id=artifact_id,
                )
            )
            continue
        if str(record.get("asset_id")) != visual.asset_id or _canonical_json(
            record.get("content_identity")
        ) != _canonical_json(dict(visual.content_identity)):
            findings.append(
                _fail(
                    "qa-receipt-asset-mismatch", QA_STATE_VISUAL_MISMATCH,
                    f"Placement receipt for role {visual.role_id} references asset "
                    f"{record.get('asset_id')} with a different content identity "
                    "than the governed selection; the persisted visual is not "
                    "the approved revision.",
                    role_id=visual.role_id,
                    receipt_asset_id=str(record.get("asset_id")),
                    expected_asset_id=visual.asset_id,
                )
            )
            continue
        post_revision = record.get("post_insertion_revision_id")
        if post_revision and str(post_revision) != observation.revision_id:
            # The artifact mutated after the verified placement: the receipt
            # no longer describes the current artifact state. Never reuse
            # stale placement evidence for terminal admission.
            findings.append(
                _fail(
                    "qa-artifact-stale", QA_STATE_ARTIFACT_STALE,
                    f"Artifact {artifact_id} revision {observation.revision_id} no "
                    f"longer matches the post-placement revision {post_revision} "
                    f"on the verified receipt for role {visual.role_id}; the "
                    "artifact mutated after placement and the visual must be "
                    "re-verified.",
                    role_id=visual.role_id,
                    post_insertion_revision_id=str(post_revision),
                    current_revision_id=observation.revision_id,
                )
            )
            continue
        if visual.marker() in observation.full_text:
            findings.append(
                _fail(
                    "qa-visual-missing", QA_STATE_VISUAL_MISSING,
                    f"Visual marker {visual.marker()} still present in the persisted "
                    f"{artifact_type} artifact; the visual for role {visual.role_id} "
                    "was not actually placed.",
                    role_id=visual.role_id, marker=visual.marker(),
                )
            )
            continue
        inserted_id = record.get("inserted_element_id")
        if inserted_id and str(inserted_id) not in observation.image_element_ids:
            findings.append(
                _fail(
                    "qa-visual-element-mismatch", QA_STATE_VISUAL_MISMATCH,
                    f"Verified receipt for role {visual.role_id} names inserted "
                    f"element {inserted_id}, but the persisted {artifact_type} "
                    "artifact contains no such element; the persisted visual "
                    "cannot be observed.",
                    role_id=visual.role_id,
                    inserted_element_id=str(inserted_id),
                )
            )
            continue
        verified_roles.append(visual.role_id)

    # Wire the existing revision/visual-completeness contract into the build
    # path (#3258 acceptance): required roles verified against the persisted
    # render, keyed to stable role identities; unresolved roles route to
    # manual review with the roles named, never to a false pass.
    revision_result = validate_revision_render_visuals(
        required_role_ids=tuple(sorted(set(required_roles_here))),
        rendered_visual_role_ids=tuple(sorted(set(verified_roles))),
        unresolved_visual_role_ids=tuple(sorted(set(unresolved_roles))),
    )
    for revision_finding in revision_result.findings:
        if revision_finding.severity == "fail":
            findings.append(
                _fail(
                    "qa-" + revision_finding.code,
                    QA_STATE_VISUAL_MISSING,
                    revision_finding.message,
                    source="worksheet_revision_qa",
                )
            )
        else:
            findings.append(
                _advisory(
                    "qa-" + revision_finding.code,
                    QA_STATE_PLACEMENT_UNVERIFIED,
                    revision_finding.message
                    + " Unresolved roles: "
                    + ", ".join(sorted(set(unresolved_roles)))
                    + ".",
                    source="worksheet_revision_qa",
                )
            )
    return findings


def evaluate_artifact_qa(
    *,
    artifact_type: str,
    artifact_id: str,
    expectations: TerminalQAExpectations | None,
    observation: ArtifactObservation,
    placement_records: tuple[dict[str, Any], ...],
    idempotency_key: str,
) -> ArtifactQAReport:
    """Evaluate one persisted artifact against its governed expectations."""
    findings: list[QAFinding] = []

    def _report(state: str, extra: list[QAFinding] | None = None) -> ArtifactQAReport:
        all_findings = findings + list(extra or ())
        worst = state
        for finding in all_findings:
            if _STATE_SEVERITY.get(finding.state, 99) > _STATE_SEVERITY.get(worst, 99):
                worst = finding.state
        return ArtifactQAReport(
            artifact_type=artifact_type,
            artifact_id=observation.artifact_id,
            revision_id=observation.revision_id,
            idempotency_key=idempotency_key,
            state=worst,
            findings=tuple(all_findings),
            expectations_hash=expectations.expectations_hash() if expectations else "",
        )

    if observation.artifact_id != artifact_id:
        findings.append(
            _fail(
                "qa-artifact-identity-conflict", QA_STATE_ARTIFACT_CONFLICT,
                f"QA inspected artifact {observation.artifact_id}, not the built "
                f"artifact {artifact_id}; evidence is not attributable.",
                inspected_artifact_id=observation.artifact_id,
                expected_artifact_id=artifact_id,
            )
        )
        return _report(QA_STATE_ARTIFACT_CONFLICT)
    if expectations is None or not expectations.idempotency_key:
        findings.append(
            _fail(
                "qa-expectations-missing", QA_STATE_EVIDENCE_INCOMPLETE,
                "No governed QA expectations were supplied for this build; "
                "terminal content cannot be proven.",
            )
        )
        return _report(QA_STATE_EVIDENCE_INCOMPLETE)
    if expectations.idempotency_key != idempotency_key:
        findings.append(
            _fail(
                "qa-build-attribution-mismatch", QA_STATE_ARTIFACT_CONFLICT,
                "QA expectations are bound to a different build idempotency key; "
                "evidence is not attributable to this build.",
                expectations_key=expectations.idempotency_key,
                build_key=idempotency_key,
            )
        )
        return _report(QA_STATE_ARTIFACT_CONFLICT)

    # Global unresolved-token scan: any surviving {{token}} fails QA with a
    # token-level finding, even for tokens outside the expectation list.
    for token in observation.token_hits[:_MAX_TOKEN_FINDINGS]:
        findings.append(
            _fail(
                "qa-token-unresolved", QA_STATE_TOKEN_UNRESOLVED,
                f"Unresolved template token {token} persists in the "
                f"{artifact_type} artifact.",
                token=token,
            )
        )
    if len(observation.token_hits) > _MAX_TOKEN_FINDINGS:
        findings.append(
            _advisory(
                "qa-token-unresolved-truncated", QA_STATE_TOKEN_UNRESOLVED,
                f"{len(observation.token_hits) - _MAX_TOKEN_FINDINGS} further "
                "unresolved tokens omitted from this report.",
                total_token_hits=len(observation.token_hits),
            )
        )

    for heading in observation.headings_without_keep_with_next:
        findings.append(
            _fail(
                "qa-heading-keep-with-next-missing", QA_STATE_LAYOUT_RULE_VIOLATED,
                f"{heading.named_style_type} heading at index {heading.start_index} "
                "lacks effective keepWithNext and can be stranded at a page foot.",
                named_style_type=heading.named_style_type,
                start_index=heading.start_index,
                end_index=heading.end_index,
            )
        )

    findings.extend(
        _evaluate_content(
            artifact_type=artifact_type,
            observation=observation,
            expectations=expectations.for_artifact(artifact_type),
        )
    )
    findings.extend(
        _evaluate_visuals(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            observation=observation,
            visual_expectations=expectations.visuals,
            placement_records=placement_records,
        )
    )
    return _report(QA_STATE_VERIFIED)


# ---------------------------------------------------------------------------
# Durable QA evidence store + terminal QA entry point
# ---------------------------------------------------------------------------

def qa_evidence_path(qa_evidence_dir: str | Path, idempotency_key: str) -> Path:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required for the QA evidence store")
    if "/" in key or "\\" in key or ".." in key:
        raise ValueError("idempotency_key is not a safe QA-evidence file name")
    return Path(qa_evidence_dir) / f"{key}.json"


def load_qa_evidence(qa_evidence_dir: str | Path, idempotency_key: str) -> dict[str, Any] | None:
    path = qa_evidence_path(qa_evidence_dir, idempotency_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("evidence_contract_version") != QA_EVIDENCE_CONTRACT:
        return None
    return payload


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def persist_qa_report(qa_evidence_dir: str | Path, report: TerminalQAReport) -> Path:
    """Persist the terminal QA report, atomically, bound to build + revisions."""
    path = qa_evidence_path(qa_evidence_dir, report.idempotency_key)
    payload = dict(report.to_dict())
    payload["evidence_contract_version"] = QA_EVIDENCE_CONTRACT
    # Top-level expectations hash for recovery comparison (both artifact
    # reports carry the same hash; the slides side is authoritative).
    payload["expectations_hash"] = report.slides.expectations_hash
    _write_atomic(path, payload)
    return path


def _try_recover_verified(
    *,
    qa_evidence_dir: str | Path,
    expectations: TerminalQAExpectations,
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
) -> ArtifactQAReport | None:
    """Recover a prior verified QA result when identity assumptions still hold.

    Reuse is allowed only when: the stored report verified this exact
    artifact, the expectations hash matches the current governed
    expectations, and the artifact revision is unchanged. Anything else
    requires fresh verification.
    """
    stored = load_qa_evidence(qa_evidence_dir, expectations.idempotency_key)
    if stored is None or stored.get("state") != QA_STATE_VERIFIED:
        return None
    key = "slides" if artifact_type == "slides" else "worksheet"
    stored_artifact = stored.get(key)
    if not isinstance(stored_artifact, dict):
        return None
    if stored_artifact.get("state") != QA_STATE_VERIFIED:
        return None
    if stored_artifact.get("artifact_id") != artifact_id:
        return None
    if stored_artifact.get("revision_id") != observation.revision_id:
        return None
    if stored.get("expectations_hash") != expectations.expectations_hash():
        return None
    findings = tuple(
        QAFinding(
            code=str(item.get("code", "")),
            severity=str(item.get("severity", "")),
            state=str(item.get("state", "")),
            message=str(item.get("message", "")),
            detail=dict(item.get("detail") or {}),
        )
        for item in stored_artifact.get("findings", [])
        if isinstance(item, dict)
    )
    return ArtifactQAReport(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        revision_id=observation.revision_id,
        idempotency_key=expectations.idempotency_key,
        state=QA_STATE_VERIFIED,
        findings=findings,
        expectations_hash=expectations.expectations_hash(),
        recovered=True,
    )


def _qa_one_artifact(
    *,
    artifact_type: str,
    artifact_id: str,
    service: Any,
    expectations: TerminalQAExpectations,
    placement_records: tuple[dict[str, Any], ...],
    qa_evidence_dir: str | Path | None,
) -> ArtifactQAReport:
    """Observe, evaluate (or recover), and persist QA for one artifact."""
    try:
        observation = observe_artifact(service, artifact_type, artifact_id)
    except VerificationRuntimeUnavailableError as exc:
        return ArtifactQAReport(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            revision_id="",
            idempotency_key=expectations.idempotency_key,
            state=QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE,
            findings=(
                _fail(
                    "qa-verification-runtime-unavailable",
                    QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE,
                    str(exc),
                ),
            ),
            expectations_hash=expectations.expectations_hash(),
        )
    except ArtifactInaccessibleError as exc:
        return ArtifactQAReport(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            revision_id="",
            idempotency_key=expectations.idempotency_key,
            state=QA_STATE_ARTIFACT_INACCESSIBLE,
            findings=(
                _fail("qa-artifact-inaccessible", QA_STATE_ARTIFACT_INACCESSIBLE, str(exc)),
            ),
            expectations_hash=expectations.expectations_hash(),
        )
    except Exception as exc:  # fail closed on unexpected QA errors
        return ArtifactQAReport(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            revision_id="",
            idempotency_key=expectations.idempotency_key,
            state=QA_STATE_EVIDENCE_INCOMPLETE,
            findings=(
                _fail(
                    "qa-evaluation-error", QA_STATE_EVIDENCE_INCOMPLETE,
                    f"Terminal QA evaluation raised {type(exc).__name__}: {exc}; "
                    "evidence is incomplete and terminal success is refused.",
                ),
            ),
            expectations_hash=expectations.expectations_hash(),
        )
    if qa_evidence_dir is not None:
        recovered = _try_recover_verified(
            qa_evidence_dir=qa_evidence_dir,
            expectations=expectations,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            observation=observation,
        )
        if recovered is not None:
            return recovered
    return evaluate_artifact_qa(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        expectations=expectations,
        observation=observation,
        placement_records=placement_records,
        idempotency_key=expectations.idempotency_key,
    )


def run_terminal_qa(
    *,
    expectations: TerminalQAExpectations | None,
    slides_service: Any,
    docs_service: Any,
    slides_file_id: str,
    worksheet_file_id: str,
    receipts_dir: str | Path | None,
    qa_evidence_dir: str | Path | None = None,
) -> TerminalQAReport:
    """Run terminal artifact-content QA for the built Slides/Docs pair.

    Fail-closed: with no governed expectations, both artifacts report
    ``evidence-incomplete`` without touching the services. Otherwise each
    artifact is observed from its persisted state and evaluated; verified
    prior evidence is recovered only while artifact revision and
    expectations still match. The report is persisted to
    ``qa_evidence_dir`` when one is supplied.
    """
    if expectations is None or not expectations.idempotency_key:
        key = ""
        empty_report = lambda artifact_type, artifact_id: ArtifactQAReport(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            revision_id="",
            idempotency_key=key,
            state=QA_STATE_EVIDENCE_INCOMPLETE,
            findings=(
                _fail(
                    "qa-expectations-missing", QA_STATE_EVIDENCE_INCOMPLETE,
                    "No governed QA expectations were supplied for this build; "
                    "terminal content cannot be proven.",
                ),
            ),
        )
        report = TerminalQAReport(
            idempotency_key=key,
            slides=empty_report("slides", slides_file_id),
            worksheet=empty_report("worksheet", worksheet_file_id),
            state=QA_STATE_EVIDENCE_INCOMPLETE,
            generated_at=_utc_now(),
        )
        return report

    placement_records: tuple[dict[str, Any], ...] = ()
    if receipts_dir is not None and expectations.visuals:
        placement_records = load_placement_records(receipts_dir, expectations.idempotency_key)

    slides_report = _qa_one_artifact(
        artifact_type="slides",
        artifact_id=slides_file_id,
        service=slides_service,
        expectations=expectations,
        placement_records=placement_records,
        qa_evidence_dir=qa_evidence_dir,
    )
    worksheet_report = _qa_one_artifact(
        artifact_type="docs",
        artifact_id=worksheet_file_id,
        service=docs_service,
        expectations=expectations,
        placement_records=placement_records,
        qa_evidence_dir=qa_evidence_dir,
    )
    overall = QA_STATE_VERIFIED
    for candidate in (slides_report.state, worksheet_report.state):
        if _STATE_SEVERITY.get(candidate, 99) > _STATE_SEVERITY.get(overall, 99):
            overall = candidate
    report = TerminalQAReport(
        idempotency_key=expectations.idempotency_key,
        slides=slides_report,
        worksheet=worksheet_report,
        state=overall,
        generated_at=_utc_now(),
    )
    if qa_evidence_dir is not None:
        persist_qa_report(qa_evidence_dir, report)
    return report
