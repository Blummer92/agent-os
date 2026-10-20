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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .placement_receipts import (
    BATCH_PROOF_CONTRACT,
    PlacementStoreIntegrityError,
    assert_no_unresolved_placement_attempts,
    batch_proof_fingerprint,
    load_receipt_store_snapshot,
    validate_batch_proof_structure,
)
from .content_spec import slide_token_index
from .slides_requests import QA_SLIDE_INDEX_KEY
from .worksheet_pagination import HeadingParagraph, heading_paragraphs
from .worksheet_revision_qa import validate_revision_render_visuals


TERMINAL_QA_CONTRACT = "terminal-artifact-content-qa-v1"
# v2 (#3416): verified evidence now includes the heading keep-with-next
# check, so v1 evidence recorded before that rule is never recovered.
QA_EVIDENCE_CONTRACT = "terminal-qa-evidence-v4"

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
QA_STATE_PLACEMENT_UNVERIFIED = "placement-unverified"
QA_STATE_PAGINATION_UNVERIFIED = "pagination-unverified"  # #3416
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
    QA_STATE_PAGINATION_UNVERIFIED: 10,
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

# Cap on headings listed in the #3416 pagination finding; the count is
# always exact.
_MAX_HEADING_DETAILS = 10


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
    # Artifact scope (#3212): "" keeps the legacy artifact-agnostic behavior
    # (a visual placed in any artifact of the build satisfies), while
    # "docs"/"slides" binds the obligation to that artifact type. Declared
    # required worksheet figures are docs-scoped: a Slides receipt must not
    # satisfy a required Docs image obligation.
    artifact_type: str = ""

    def marker(self) -> str:
        return "{{visual:" + self.role_id + "}}"


@dataclass(frozen=True)
class TerminalQAExpectations:
    """The governed expectations terminal QA evaluates the artifact against."""

    idempotency_key: str
    docs_content: tuple[ContentExpectation, ...] = ()
    slides_content: tuple[ContentExpectation, ...] = ()
    visuals: tuple[VisualExpectation, ...] = ()
    # #3259 D2: the authored content-token set the composer verified the
    # plan covers. Bound into the expectations identity so a truncated plan
    # can never be mistaken for a complete one at recovery time.
    expected_content_tokens: tuple[str, ...] = ()

    @staticmethod
    def build_from_requests(
        *,
        idempotency_key: str,
        docs_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        slides_requests: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        visual_placements: tuple[Any, ...] = (),
        required_docs_visuals: tuple[tuple[str, str], ...] = (),
        expected_content_tokens: tuple[str, ...] | list[str] | None = None,
    ) -> "TerminalQAExpectations":
        """Derive expectations from the governed planned build inputs.

        Content expectations come from the planned ``replaceAllText``
        requests: the ``containsText`` token must be gone from the persisted
        artifact and the ``replaceText`` must be present. Visual expectations
        come from the Wave 3 placement bindings (role/slot/asset/exact
        content identity). Nothing is inferred beyond these governed inputs.

        ``required_docs_visuals`` carries the lesson-declared required
        worksheet figures as ``(role_id, slot_id)`` pairs (#3212). Each one
        is a required Docs target: it must be backed by a *required*
        placement binding (an optional binding cannot discharge it), and the
        resulting expectation is docs-scoped so only a verified Docs receipt
        satisfies it. A missing or optional-only backing binding fails
        closed here, at composition time, instead of shipping a worksheet
        whose required figure has no governed placement.

        ``expected_content_tokens`` records the authored token set the
        shared composer verified the plan covers (#3259 D2); it is bound
        into the expectations identity but never generates expectations.
        """
        visuals = [
            VisualExpectation(
                role_id=str(binding.role_id),
                slot_id=str(binding.slot_id),
                asset_id=str(binding.asset_id),
                content_identity=dict(binding.content_identity or {}),
                required=bool(binding.required),
            )
            for binding in visual_placements or ()
        ]
        for role_id, slot_id in required_docs_visuals or ():
            target = (str(role_id), str(slot_id))
            matches = [
                visual for visual in visuals
                if (visual.role_id, visual.slot_id) == target
            ]
            if not matches:
                raise ValueError(
                    "declared required worksheet figure "
                    f"{target[0]}:{target[1]} has no governed placement binding; "
                    "the required Docs image obligation cannot be proven"
                )
            if not any(visual.required for visual in matches):
                raise ValueError(
                    "declared required worksheet figure "
                    f"{target[0]}:{target[1]} is backed only by optional "
                    "placement bindings; an optional binding cannot satisfy a "
                    "required Docs image obligation"
                )
            visuals = [
                replace(visual, artifact_type="docs")
                if (visual.role_id, visual.slot_id) == target and visual.required
                else visual
                for visual in visuals
            ]
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
            visuals=tuple(visuals),
            expected_content_tokens=tuple(sorted(set(expected_content_tokens or ()))),
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
                 "content_identity": dict(v.content_identity), "required": v.required,
                 "artifact_type": v.artifact_type}
                for v in self.visuals
            ],
            # #3259 D2: the authored token set is part of the expectations
            # identity. Pre-repair evidence (recorded without it) can never
            # hash-match a repaired build's expectations, so a truncated
            # plan's VERIFIED is never recovered.
            "expected_content_tokens": sorted(self.expected_content_tokens),
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
    location_hint: Mapping[str, Any] | None = None
    if artifact_type == "slides" and isinstance(request, Mapping):
        authored_index = request.get(QA_SLIDE_INDEX_KEY)
        if (
            isinstance(authored_index, int)
            and not isinstance(authored_index, bool)
            and authored_index >= 1
        ):
            # Bind the authored slide identity to the observed readback
            # position. Governed template convention: the title/objectives
            # slide is read back at position 0 and authored slide n follows
            # at position n, so the 0-based observed position equals the
            # authored 1-based index. The identity comes from the authored
            # LessonContent via the request builder -- never inferred from
            # unverified observed order.
            location_hint = {"slide_index": authored_index}
    return ContentExpectation(
        artifact_type=artifact_type, token=token, expected_text=expected,
        location_hint=location_hint,
    )


def _is_slide_scoped_token(token: str) -> bool:
    """Whether a content token is slide-scoped under the governed convention.

    Slide-scoped tokens (``{{slide_<index>_heading}}`` /
    ``{{slide_<index>_bullet_<n>}}``) name one authored slide and must be
    proven at that slide's location. Everything else (``{{title}}``,
    ``{{objective_N}}``, ``{{question_N}}``, context tokens) is
    presentation-wide and keeps whole-artifact scope.
    """
    name = token
    if isinstance(name, str) and name.startswith("{{") and name.endswith("}}"):
        name = name[2:-2]
    return slide_token_index(name) is not None


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
    observed_at: str = ""
    headings: tuple[HeadingParagraph, ...] = ()  # #3416; () for slides
    # Only actual Slides image objects qualify; key -> actual slide objectId.
    image_element_containers: Mapping[str, str] = field(default_factory=dict)


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
    placement_evidence_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": TERMINAL_QA_CONTRACT,
            "idempotency_key": self.idempotency_key,
            "state": self.state,
            "generated_at": self.generated_at,
            "placement_evidence_hash": self.placement_evidence_hash,
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


def _slides_text_and_images(
    presentation: Mapping[str, Any],
) -> tuple[list[str], list[str], dict[str, str]]:
    """Extract text and actual image IDs, preserving each image's slide.

    Object IDs of shapes, tables, and lines are never image evidence.
    Ambiguous duplicate image IDs lose their location proof.
    """
    slide_texts: list[str] = []
    element_ids: list[str] = []
    image_containers: dict[str, str] = {}
    slides = presentation.get("slides")
    if not isinstance(slides, list):
        return [], [], {}
    for slide in slides:
        if not isinstance(slide, dict):
            slide_texts.append("")
            continue
        parts: list[str] = []
        slide_id = slide.get("objectId")
        for element in slide.get("pageElements", []):
            if not isinstance(element, dict):
                continue
            object_id = element.get("objectId")
            if (isinstance(object_id, str) and object_id
                    and isinstance(element.get("image"), dict)):
                element_ids.append(object_id)
                if isinstance(slide_id, str) and slide_id:
                    if object_id in image_containers:
                        image_containers[object_id] = ""  # ambiguous ID, fail closed
                    else:
                        image_containers[object_id] = slide_id
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
    return slide_texts, element_ids, image_containers


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
    image_containers: dict[str, str] = {}
    if artifact_type == "docs":
        full_text, image_ids = _docs_text_and_images(resource)
        slide_texts: tuple[str, ...] = ()
        headings = heading_paragraphs(resource)
    else:
        slide_texts_list, image_ids, image_containers = _slides_text_and_images(resource)
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
        observed_at=_utc_now(),
        headings=headings,
        image_element_containers=image_containers,
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
        hint = expectation.location_hint
        if not isinstance(hint, Mapping):
            hint = {}
        slide_index = hint.get("slide_index")
        if artifact_type == "slides" and _is_slide_scoped_token(expectation.token):
            # Slide-scoped expectations must prove content at the governed
            # slide location. A missing or unresolvable hint fails closed
            # (evidence-incomplete) instead of silently widening scope to the
            # whole presentation.
            if (
                not isinstance(slide_index, int)
                or isinstance(slide_index, bool)
                or not 0 <= slide_index < len(observation.slide_texts)
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
        else:
            # Presentation-wide tokens (title, objective_N, ...) and every
            # docs expectation keep whole-artifact scope.
            scope_text = observation.full_text
            normalized_scope = normalized_full
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


def _evaluate_pagination(observation: ArtifactObservation) -> list[QAFinding]:
    """#3416: every worksheet heading must keep with its following content."""
    unkept = [heading for heading in observation.headings if not heading.keep_with_next]
    if not unkept:
        return []
    return [
        _fail(
            "qa-heading-keep-with-next-missing", QA_STATE_PAGINATION_UNVERIFIED,
            f"{len(unkept)} worksheet heading(s) lack an effective keepWithNext "
            "and can be stranded at the bottom of a page, apart from their "
            "section.",
            count=len(unkept),
            headings=[
                {"start_index": heading.start_index,
                 "named_style_type": heading.named_style_type,
                 "text": heading.text[:80]}
                for heading in unkept[:_MAX_HEADING_DETAILS]
            ],
        )
    ]


def _verify_single_batch_proof(
    *,
    proof: Mapping[str, Any],
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
    placement_records: tuple[dict[str, Any], ...],
) -> tuple[str, dict[tuple[str, str], Mapping[str, Any]], list[QAFinding]]:
    """Verify one reconciled batch proof against the current observation.

    Returns (status, members, findings) where status is "verified",
    "invalid" (tampered/corrupt/conflicting), or "stale" (the artifact
    moved after reconciliation). Members maps (role_id, slot_id) to the
    proof's member entries. A missing (when required), conflicting, or
    tampered proof is never verification: callers route those to manual
    review.

    Structural validation runs BEFORE any member iteration, fingerprint
    verification, or membership reconciliation: malformed evidence fails
    closed here instead of crashing iteration or being silently skipped.
    """
    structure_issues = validate_batch_proof_structure(proof)
    if structure_issues:
        return (
            "invalid",
            {},
            [
                _fail(
                    "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                    f"Batch placement proof for {artifact_type} {artifact_id} "
                    "is structurally malformed "
                    f"({'; '.join(structure_issues)}); the proof cannot be "
                    "trusted. Manual review required; the batch is not "
                    "verified.",
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    structure_issues=list(structure_issues),
                )
            ],
        )
    claimed: dict[tuple[str, str], Mapping[str, Any]] = {}
    # Structurally validated above: ordered_members is a non-empty list of
    # mappings with unique (role_id, slot_id) keys, so no silent skips or
    # collapses are possible here.
    for member in proof.get("ordered_members") or ():
        claimed[(str(member.get("role_id")), str(member.get("slot_id")))] = member
    stored_fingerprint = proof.get("proof_fingerprint")
    if (
        not isinstance(stored_fingerprint, str)
        or not stored_fingerprint
        or stored_fingerprint != batch_proof_fingerprint(proof)
    ):
        return (
            "invalid",
            claimed,
            [
                _fail(
                    "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                    f"Batch placement proof for {artifact_type} {artifact_id} "
                    "failed fingerprint verification; the proof was tampered "
                    "with or corrupted. Manual review required; the batch is "
                    "not verified.",
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                )
            ],
        )
    if str(proof.get("final_revision_id")) != observation.revision_id:
        return (
            "stale",
            claimed,
            [
                _fail(
                    "qa-artifact-stale", QA_STATE_ARTIFACT_STALE,
                    f"Artifact {artifact_id} revision {observation.revision_id} "
                    "no longer matches the reconciled batch proof revision "
                    f"{proof.get('final_revision_id')}; the artifact mutated "
                    "after reconciliation and the batch must be re-verified. "
                    "Manual review required.",
                    proof_final_revision_id=str(proof.get("final_revision_id")),
                    current_revision_id=observation.revision_id,
                )
            ],
        )
    members: dict[tuple[str, str], Mapping[str, Any]] = {}
    for key, member in claimed.items():
        match: dict[str, Any] | None = None
        for record in placement_records:
            if (
                record.get("state") == "verified"
                and str(record.get("role_id")) == key[0]
                and str(record.get("slot_id")) == key[1]
                and record.get("artifact_type") == artifact_type
                and str(record.get("artifact_id")) == artifact_id
                and _canonical_json(record.get("content_identity"))
                == _canonical_json(member.get("content_identity"))
            ):
                match = record
                break
        if match is None:
            return (
                "invalid",
                claimed,
                [
                    _fail(
                        "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                        f"Batch proof member role={key[0]} slot={key[1]} has no "
                        "matching stored verified receipt; the proof's member "
                        "set conflicts with the receipt store. Manual review "
                        "required.",
                        role_id=key[0], slot_id=key[1],
                    )
                ],
            )
        for field in ("asset_id", "inserted_element_id", "post_insertion_revision_id"):
            if str(match.get(field)) != str(member.get(field)):
                return (
                    "invalid",
                    claimed,
                    [
                        _fail(
                            "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                            f"Batch proof member role={key[0]} slot={key[1]} "
                            f"diverges from its stored receipt on {field}; "
                            "conflicting evidence. Manual review required.",
                            role_id=key[0], slot_id=key[1], field=field,
                        )
                    ],
                )
        element_id = str(member.get("inserted_element_id") or "")
        if element_id not in observation.image_element_ids:
            return (
                "stale",
                claimed,
                [
                    _fail(
                        "qa-visual-element-mismatch", QA_STATE_VISUAL_MISMATCH,
                        f"Batch proof member role={key[0]} slot={key[1]} names "
                        f"inserted element {element_id}, but the persisted "
                        f"{artifact_type} artifact contains no such element; "
                        "the persisted visual cannot be observed.",
                        role_id=key[0], slot_id=key[1],
                        inserted_element_id=element_id,
                    )
                ],
            )
        members[key] = member
    # #3258 P1-2: exact BIDIRECTIONAL membership. The loop above enforces
    # proof->receipts (every claimed member matches a stored verified
    # receipt); this enforces receipts->proof (every verified receipt for
    # this artifact is claimed by exactly one proof member). A proof that
    # silently drops a member while the receipt survives is conflicting
    # evidence, never verification.
    verified_receipt_keys = {
        (str(record.get("role_id")), str(record.get("slot_id")))
        for record in placement_records
        if record.get("state") == "verified"
        and record.get("artifact_type") == artifact_type
        and str(record.get("artifact_id")) == artifact_id
    }
    unclaimed = sorted(verified_receipt_keys - set(claimed.keys()))
    if unclaimed:
        return (
            "invalid",
            claimed,
            [
                _fail(
                    "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                    f"{len(unclaimed)} verified placement receipt(s) for "
                    f"{artifact_type} {artifact_id} "
                    f"({', '.join(f'role={role} slot={slot}' for role, slot in unclaimed)}) "
                    "are not claimed by the reconciled batch proof; the "
                    "proof's member set is incomplete. Manual review "
                    "required; the batch is not verified.",
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    unclaimed_members=[
                        {"role_id": role, "slot_id": slot}
                        for role, slot in unclaimed
                    ],
                )
            ],
        )
    return ("verified", members, [])


def _resolve_batch_proof(
    batch_proofs: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None,
    *,
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
    placement_records: tuple[dict[str, Any], ...],
) -> tuple[str, dict[tuple[str, str], Mapping[str, Any]], list[QAFinding]]:
    """Select and verify the batch proof for one artifact.

    Status "absent" carries no findings by itself; the caller applies the
    strict missing-proof rule (a multi-receipt batch without its
    reconciled proof fails closed). "conflict"/"invalid"/"stale" each
    carry their own fail-closed finding; "verified" carries the
    revalidated member map terminal QA may consume. The proof-side
    artifact field is ``batch_artifact_type`` (deliberately distinct from
    the receipt envelope's ``artifact_type``).
    """
    candidates = [
        proof for proof in batch_proofs or ()
        if isinstance(proof, dict)
        and proof.get("proof_contract") == BATCH_PROOF_CONTRACT
        and proof.get("batch_artifact_type") == artifact_type
        and str(proof.get("artifact_id")) == artifact_id
    ]
    if not candidates:
        return ("absent", {}, [])
    if len(candidates) > 1:
        return (
            "conflict",
            {},
            [
                _fail(
                    "qa-batch-proof-conflict", QA_STATE_ARTIFACT_CONFLICT,
                    f"{len(candidates)} batch placement proofs claim "
                    f"{artifact_type} {artifact_id}; conflicting evidence. "
                    "Manual review required; the batch is not verified.",
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    proof_count=len(candidates),
                )
            ],
        )
    return _verify_single_batch_proof(
        proof=candidates[0],
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        observation=observation,
        placement_records=placement_records,
    )


def _batch_proof_required_but_missing(
    *,
    placement_records: tuple[dict[str, Any], ...],
    artifact_type: str,
    artifact_id: str,
) -> bool:
    """Whether this artifact's receipt set requires a reconciled batch proof.

    A batch proof is required when the store holds more than one verified
    placement receipt for this artifact: sequential insertions each
    advance the artifact revision, and only the reconciled proof's
    verified per-insertion continuity can legitimately re-bind that
    receipt set to the observed final revision. The governed placement
    path always persists the proof, so a multi-receipt batch without one
    is unproven evidence and must fail closed (strict fail-closed; there
    is no permissive per-receipt fallback for the batch case).
    """
    verified_here = [
        record for record in placement_records
        if record.get("state") == "verified"
        and record.get("artifact_type") == artifact_type
        and str(record.get("artifact_id")) == str(artifact_id)
    ]
    return len(verified_here) > 1


def _evaluate_visuals(
    *,
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
    visual_expectations: tuple[VisualExpectation, ...],
    placement_records: tuple[dict[str, Any], ...],
    batch_proofs: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = (),
) -> list[QAFinding]:
    findings: list[QAFinding] = []
    verified_roles: list[str] = []
    unresolved_roles: list[str] = []
    required_roles_here: list[str] = []

    # #3258: a verified reconciled batch proof re-binds the ordered complete
    # receipt set to the observed final revision, so members it revalidates
    # are not rejected as stale for their original per-insertion revisions.
    # Conflicting, invalid, or stale proofs fail closed with their own
    # finding, never verify. A missing proof is strict fail-closed exactly
    # when the proof is required (multi-receipt batch): there is no
    # permissive per-receipt fallback for the batch case.
    proof_status, proof_members, proof_findings = _resolve_batch_proof(
        batch_proofs,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        observation=observation,
        placement_records=placement_records,
    )
    findings.extend(proof_findings)
    proof_required_missing = (
        proof_status == "absent"
        and _batch_proof_required_but_missing(
            placement_records=placement_records,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
        )
    )
    if proof_required_missing:
        verified_count = sum(
            1 for r in placement_records
            if r.get("state") == "verified"
            and r.get("artifact_type") == artifact_type
            and str(r.get("artifact_id")) == str(artifact_id)
        )
        findings.append(
            _fail(
                "qa-batch-proof-missing", QA_STATE_ARTIFACT_STALE,
                f"No reconciled batch proof exists for the {verified_count} "
                f"verified placement receipts in {artifact_type} {artifact_id}; "
                "a multi-receipt batch cannot be admitted without its "
                "reconciled continuity proof. Manual review required; the "
                "batch is not verified.",
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                verified_receipt_count=verified_count,
            )
        )

    for visual in visual_expectations:
        if visual.artifact_type and visual.artifact_type != artifact_type:
            # The obligation is scoped to a different artifact type; it is
            # not expected in this one. Declared required worksheet figures
            # are docs-scoped, so the slides-side evaluation skips them here
            # instead of treating them as slides obligations (#3212).
            continue
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
            if visual.required and visual.artifact_type:
                # A required artifact-scoped visual was verified-placed only
                # in other artifacts: a Slides receipt must not satisfy a
                # required Docs image obligation, and vice versa (#3212).
                findings.append(
                    _fail(
                        "qa-visual-wrong-artifact", QA_STATE_VISUAL_MISMATCH,
                        f"Required {visual.artifact_type} visual role "
                        f"{visual.role_id} (slot {visual.slot_id}) has verified "
                        "placement receipts only in other artifacts; the "
                        f"inspected {artifact_type} artifact {artifact_id} "
                        "carries no verified placement for it.",
                        role_id=visual.role_id, slot_id=visual.slot_id,
                        expected_artifact_type=visual.artifact_type,
                        inspected_artifact_type=artifact_type,
                    )
                )
                continue
            # Placed in another artifact (marker routing); not expected here.
            continue
        if visual.required:
            required_roles_here.append(visual.role_id)
        proof_key = (visual.role_id, str(visual.slot_id))
        if proof_status in ("stale", "invalid", "conflict") and (
            proof_status == "conflict" or proof_key in proof_members
        ):
            # The batch proof already failed this visual with its own
            # fail-closed finding; do not re-verify or double-report it.
            continue
        if proof_required_missing and records_here:
            # The missing-proof finding above already failed this visual
            # closed; without a reconciled proof its receipts must not be
            # re-verified through the per-receipt fallback.
            continue
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
        # #3258: a member revalidated by a verified batch proof is bound to
        # the proof's observed final revision, not to its original
        # per-insertion revision. Without such a proof the revision-chain
        # rule stands: only the uniquely recorded, verified same-artifact
        # placement chain is accepted; all other drift fails closed.
        # The original per-insertion revisions are never rewritten.
        if proof_status == "verified" and proof_key not in proof_members:
            # #3258 P1-2: a verified proof claims every verified receipt for
            # this artifact (bidirectional membership is enforced in
            # _verify_single_batch_proof), so a visual outside the proof's
            # member set must NOT fall back to the per-receipt
            # revision-chain rule -- that fallback admitted shrunken proofs.
            findings.append(
                _fail(
                    "qa-batch-proof-invalid", QA_STATE_ARTIFACT_CONFLICT,
                    f"Visual for role {visual.role_id} slot {visual.slot_id} "
                    f"is not claimed by the verified reconciled batch proof "
                    f"for {artifact_type} {artifact_id}; a visual outside the "
                    "proof's member set cannot be admitted through the "
                    "per-receipt rule. Manual review required.",
                    role_id=visual.role_id, slot_id=visual.slot_id,
                    artifact_type=artifact_type, artifact_id=artifact_id,
                )
            )
            continue
        proof_covers = proof_status == "verified" and proof_key in proof_members
        # Preview consumers reuse the pure content expectations without
        # importing the provider/write path used only for visual validation.
        from .connected_visual_placement import _revision_chain_is_current

        if not proof_covers and not _revision_chain_is_current(record, placement_records, observation.revision_id):
            # Later image insertions may legitimately advance the artifact
            # revision. Accept only the uniquely recorded, verified
            # same-artifact placement chain; reject all other drift.
            findings.append(
                _fail(
                    "qa-artifact-stale", QA_STATE_ARTIFACT_STALE,
                    f"Artifact {artifact_id} revision {observation.revision_id} "
                    f"cannot be reached from placement revision {post_revision} "
                    f"for role {visual.role_id} through a unique verified "
                    "placement chain; external or unaccounted mutation "
                    "requires re-verification.",
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
        if not inserted_id:
            findings.append(
                _fail(
                    "qa-visual-element-missing", QA_STATE_PLACEMENT_UNVERIFIED,
                    f"Receipt for role {visual.role_id} has no inserted-element "
                    "identity, so the actual visual cannot be verified.",
                    role_id=visual.role_id,
                )
            )
            continue
        if str(inserted_id) not in observation.image_element_ids:
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
        if artifact_type == "slides":
            expected_slide = record.get("container_id")
            actual_slide = observation.image_element_containers.get(str(inserted_id))
            if (not isinstance(expected_slide, str) or not expected_slide
                    or actual_slide != expected_slide):
                findings.append(
                    _fail(
                        "qa-visual-container-mismatch", QA_STATE_VISUAL_MISMATCH,
                        f"Image {inserted_id} for role {visual.role_id} is not "
                        f"observed as an image on recorded slide {expected_slide!r}; "
                        f"actual slide is {actual_slide!r}.",
                        role_id=visual.role_id, inserted_element_id=str(inserted_id),
                        expected_container_id=expected_slide,
                        observed_container_id=actual_slide,
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
    batch_proofs: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = (),
) -> ArtifactQAReport:
    """Evaluate one persisted artifact against its governed expectations."""
    findings: list[QAFinding] = []
    # #3258: only this build's proofs are consumable here.
    proofs_for_build = tuple(
        proof for proof in batch_proofs or ()
        if isinstance(proof, dict) and str(proof.get("idempotency_key") or "") == idempotency_key
    )

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

    findings.extend(
        _evaluate_content(
            artifact_type=artifact_type,
            observation=observation,
            expectations=expectations.for_artifact(artifact_type),
        )
    )
    findings.extend(_evaluate_pagination(observation))
    findings.extend(
        _evaluate_visuals(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            observation=observation,
            visual_expectations=expectations.visuals,
            placement_records=placement_records,
            batch_proofs=proofs_for_build,
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


def _parse_recovery_findings(raw: Any) -> tuple[tuple[QAFinding, ...], bool]:
    """Defensively parse cached findings for recovery. Never raises.

    Returns ``(findings, malformed)``. Valid ``persist_qa_report`` output
    always stores findings as a list of mappings with string
    code/severity/state/message and a mapping (or absent) detail. The parse
    itself never raises: null becomes empty, non-dict items are skipped, and
    non-mapping detail is coerced to ``{}`` -- but any such deviation still
    marks the payload malformed so the caller refuses recovery instead of
    trusting it.
    """
    if raw is None:
        return (), True
    if not isinstance(raw, (list, tuple)):
        return (), True
    findings: list[QAFinding] = []
    malformed = False
    for item in raw:
        if not isinstance(item, dict):
            malformed = True
            continue
        detail = item.get("detail")
        if detail is None:
            detail = {}
        elif not isinstance(detail, Mapping):
            detail = {}
            malformed = True
        code = item.get("code")
        severity = item.get("severity")
        state = item.get("state")
        message = item.get("message")
        if not (
            isinstance(code, str)
            and isinstance(severity, str)
            and isinstance(state, str)
            and isinstance(message, str)
        ):
            malformed = True
            continue
        findings.append(
            QAFinding(
                code=code, severity=severity, state=state,
                message=message, detail=detail,
            )
        )
    return tuple(findings), malformed


def _try_recover_verified(
    *,
    qa_evidence_dir: str | Path,
    expectations: TerminalQAExpectations,
    artifact_type: str,
    artifact_id: str,
    observation: ArtifactObservation,
    placement_evidence_hash: str | None,
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
    # D2 (a): the evidence file is located by the current idempotency key,
    # but the payload's own top-level identity must also match -- a planted
    # file carrying a foreign build identity must never be recovered.
    if stored.get("idempotency_key") != expectations.idempotency_key:
        return None
    # D2 (b): the report contract version (top level and, below, nested) must
    # equal the canonical report contract. The envelope evidence-contract
    # version is already enforced by load_qa_evidence.
    if stored.get("contract_version") != TERMINAL_QA_CONTRACT:
        return None
    key = "slides" if artifact_type == "slides" else "worksheet"
    stored_artifact = stored.get(key)
    if not isinstance(stored_artifact, dict):
        return None
    # D2 (a)/(c): the nested build identity must match; the nested report must
    # carry its required identity fields. Any missing field fails the
    # comparison below and refuses recovery.
    if stored_artifact.get("idempotency_key") != expectations.idempotency_key:
        return None
    # D2 (b): nested report contract version.
    if stored_artifact.get("contract_version") != TERMINAL_QA_CONTRACT:
        return None
    if stored_artifact.get("state") != QA_STATE_VERIFIED:
        return None
    if stored_artifact.get("artifact_id") != artifact_id:
        return None
    if stored_artifact.get("revision_id") != observation.revision_id:
        return None
    if stored.get("expectations_hash") != expectations.expectations_hash():
        return None
    # #3259 D2 second layer: never recover a VERIFIED whose plan-derived
    # expectations do not cover the authored token set bound into the
    # expectations at compose time. Coverage is per artifact -- the
    # demonstrated defect truncated the Docs plan only. A truncated plan
    # that bypassed the shared composer cannot be blessed by recovery.
    expected_tokens = set(expectations.expected_content_tokens or ())
    if expected_tokens:
        # ContentExpectation.token carries the braced marker ({{token}});
        # the authored set carries bare tokens -- compare on bare form.
        def _bare(token: str) -> str:
            if (
                isinstance(token, str)
                and token.startswith("{{")
                and token.endswith("}}")
                and len(token) > 4
            ):
                return token[2:-2]
            return token

        docs_planned = {_bare(e.token) for e in expectations.docs_content}
        slides_planned = {_bare(e.token) for e in expectations.slides_content}
        if not (expected_tokens <= docs_planned and expected_tokens <= slides_planned):
            return None
    # The positive cache is valid only for the exact current receipt snapshot.
    # None means the placement evidence is unavailable/invalid; never recover.
    if placement_evidence_hash is None or stored.get("placement_evidence_hash") != placement_evidence_hash:
        return None
    # D2 (d)/(e)/(f): cached findings are untrusted -- parse defensively
    # (never raise) and require coherence with the claimed VERIFIED state.
    findings, findings_malformed = _parse_recovery_findings(
        stored_artifact.get("findings")
    )
    if findings_malformed:
        return None
    for finding in findings:
        # (e) a VERIFIED report must not carry failure findings ...
        if finding.severity == "fail":
            return None
        # (f) ... nor findings whose state contradicts the terminal state.
        if _STATE_SEVERITY.get(finding.state, 99) != _STATE_SEVERITY[QA_STATE_VERIFIED]:
            return None
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
    placement_evidence_hash: str | None,
    pending_attempt_issue: str | None,
    qa_evidence_dir: str | Path | None,
    batch_proofs: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = (),
) -> ArtifactQAReport:
    """Observe, evaluate (or recover), and persist QA for one artifact."""
    # Attempt evidence is separate from verified receipt JSON. A pending
    # fence MUST block both fresh admission and cached success, including
    # an optional-only or now-abandoned visual binding.
    if pending_attempt_issue is not None:
        return ArtifactQAReport(
            artifact_type=artifact_type, artifact_id=artifact_id, revision_id="",
            idempotency_key=expectations.idempotency_key,
            state=QA_STATE_EVIDENCE_INCOMPLETE,
            findings=(_fail(
                "qa-placement-attempt-unresolved", QA_STATE_EVIDENCE_INCOMPLETE,
                "A placement attempt has an unresolved or invalid durable fence; "
                "terminal verification is blocked: " + pending_attempt_issue,
            ),),
            expectations_hash=expectations.expectations_hash(),
        )
    if expectations.visuals and placement_evidence_hash is None:
        return ArtifactQAReport(
            artifact_type=artifact_type, artifact_id=artifact_id, revision_id="",
            idempotency_key=expectations.idempotency_key,
            state=QA_STATE_EVIDENCE_INCOMPLETE,
            findings=(_fail(
                "qa-placement-evidence-unavailable", QA_STATE_EVIDENCE_INCOMPLETE,
                "Placement evidence is malformed, unreadable, or unavailable; "
                "terminal success is refused.",
            ),),
            expectations_hash=expectations.expectations_hash(),
        )
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
        try:
            recovered = _try_recover_verified(
                qa_evidence_dir=qa_evidence_dir,
                expectations=expectations,
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                observation=observation,
                placement_evidence_hash=placement_evidence_hash,
            )
        except Exception:
            # A malformed cache must fail closed (fresh verification), never
            # crash terminal QA.
            recovered = None
        if recovered is not None:
            return recovered
    return evaluate_artifact_qa(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        expectations=expectations,
        observation=observation,
        placement_records=placement_records,
        idempotency_key=expectations.idempotency_key,
        batch_proofs=batch_proofs,
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
    prior evidence is recovered only while the exact stored receipt bytes
    (records plus reconciled batch proofs, via the placement evidence
    hash), artifact revision, and expectations still match. Terminal
    visual evaluation consumes the reconciled batch proof (#3258) for
    members it revalidates; a missing (when required), conflicting, or
    tampered proof fails closed for manual review, never verification.
    The report is persisted to ``qa_evidence_dir`` when one is supplied.
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
    placement_evidence_hash: str | None = "no-visual-expectations"
    batch_proofs: tuple[dict[str, Any], ...] = ()
    if expectations.visuals:
        placement_evidence_hash = None
        if receipts_dir is not None:
            # #3258 P1-3: single-snapshot read. Records, batch proofs, and
            # the evidence hash all derive from the same store bytes, so a
            # writer landing mid-read cannot mix receipts from one snapshot
            # with proofs from another (the old two-read sequence let
            # mixed evidence verify). The hash still binds every proof
            # change into recovery: any proof change refuses cached
            # verified QA.
            (
                placement_records,
                batch_proofs,
                placement_evidence_hash,
            ) = load_receipt_store_snapshot(
                receipts_dir, expectations.idempotency_key,
            )

    pending_attempt_issue: str | None = None
    if receipts_dir is not None:
        try:
            assert_no_unresolved_placement_attempts(
                receipts_dir, expectations.idempotency_key,
            )
        except PlacementStoreIntegrityError as exc:
            pending_attempt_issue = str(exc)

    slides_report = _qa_one_artifact(
        artifact_type="slides",
        artifact_id=slides_file_id,
        service=slides_service,
        expectations=expectations,
        placement_records=placement_records,
        placement_evidence_hash=placement_evidence_hash,
        pending_attempt_issue=pending_attempt_issue,
        qa_evidence_dir=qa_evidence_dir,
        batch_proofs=batch_proofs,
    )
    worksheet_report = _qa_one_artifact(
        artifact_type="docs",
        artifact_id=worksheet_file_id,
        service=docs_service,
        expectations=expectations,
        placement_records=placement_records,
        placement_evidence_hash=placement_evidence_hash,
        pending_attempt_issue=pending_attempt_issue,
        qa_evidence_dir=qa_evidence_dir,
        batch_proofs=batch_proofs,
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
        placement_evidence_hash=placement_evidence_hash,
    )
    if qa_evidence_dir is not None:
        persist_qa_report(qa_evidence_dir, report)
    return report

