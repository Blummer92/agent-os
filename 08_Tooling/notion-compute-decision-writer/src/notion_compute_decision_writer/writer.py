"""Offline-first Notion Compute Decision writer for #1424.

Consumes an already-computed and already-serialized #1419 compute-control
projection payload (schema ``agent-os-compute-control-projection/1.0``,
itself built on the #1097 Coding Command Center handoff) and prepares one
bounded update plan for an existing Notion ``Tasks / Issues`` record. Follows
the #1003 destination-local pre-write reconciliation decision (exact
identity, fail-closed ambiguity, no generic sync framework) and the
#1420-frozen destination/presentation contract: data source
``5216eacf-639d-4881-92bc-a634ead56669``, ``Compute Decision`` is the only
writable field, and ``Source Link`` is the identity anchor and is never
rewritten.

The #1419 projection is consumed by schema reference only -- its dataclass is
deliberately not imported. That keeps this package a self-contained,
dependency-free destination-local adapter (mirroring #1419's own choice to
mirror the validation-head vocabulary by reference rather than import it) and
means this module recalculates no authorization, validation, routing,
currentness, or compute disposition; it only reads the frozen, versioned
contract #1419 already produced.

This module performs no GitHub, network, filesystem, subprocess, Scheduler,
or Notion I/O of its own. Live mutation requires a separately authorized
injected client and remains gated by the #1420 Change Request; ``dry_run=True``
is the default and makes zero client calls.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Literal, Protocol, TypeVar

MAX_TEXT = 2000
MAX_RETRIES = 5
MAX_TOTAL_RETRY_DELAY = 120.0

# Frozen by the #1420 live target inspection recorded on the #1424 activation
# checkpoint. Not configurable here: a request for any other data source is a
# precheck failure, not a routing choice.
DATA_SOURCE_ID = "5216eacf-639d-4881-92bc-a634ead56669"

# The #1419 schema this adapter accepts. #1419 owns bumping this; a payload
# claiming a different name/version fails closed rather than being guessed at.
COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME = "agent-os-compute-control-projection"
COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION = "1.0"

# Mirrors the finite #1419 disposition vocabulary by reference (plain string
# values only, matching ComputeDisposition.value in
# scripts/agent_os_issue_acceptance/compute_control_projection.py) rather than
# importing that package. #1419 remains the sole owner of computing these
# values; this module only maps an already-computed one to display text.
COMPUTE_DECISION_PRESENTATION: dict[str, str] = {
    "run-now": "Run Now",
    "do-not-spend-compute-yet": "Do Not Spend Compute Yet",
    "focused-validation-first": "Focused Validation First",
    "final-cloud-validation-required": "Final Cloud Validation Required",
    "reuse-existing-evidence": "Reuse Existing Evidence",
    "duplicate-or-obsolete-run-risk": "Duplicate / Obsolete Run Risk",
    "unavailable": "Verify Current State",
}

WRITABLE_LOGICAL_FIELDS = frozenset({"compute_decision"})

# Reason codes #1419 itself uses to signal that its projection is not current
# for the identity it claims to describe. Reading them here is consuming an
# already-computed signal, not recalculating currentness.
_STALE_PROJECTION_REASON_CODES = frozenset(
    {
        "compute.fail-closed-currentness",
        "compute.head-identity-conflict",
        "compute.plan-identity-mismatch",
    }
)

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

T = TypeVar("T")


class WriteState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    UPDATED = "UPDATED"
    UNCHANGED_SKIP = "UNCHANGED_SKIP"
    AMBIGUOUS_WRITE_RESULT = "AMBIGUOUS_WRITE_RESULT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    """The caller's freshly reacquired canonical identity for this issue.

    Used only to detect whether the supplied #1419 projection is stale
    relative to what the caller currently believes is canonical -- never to
    recompute currentness itself.
    """

    repository: str
    issue_number: int
    current_head_sha: str

    def __post_init__(self) -> None:
        if not _text(self.repository) or "/" not in self.repository:
            raise ValueError("repository must be an exact owner/name string")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ValueError("issue_number must be a positive built-in integer")
        if not _sha40(self.current_head_sha):
            raise ValueError("current_head_sha must be a lowercase 40-character SHA")


@dataclass(frozen=True, slots=True)
class ComputeControlProjectionEvidence:
    """The bounded subset of the #1419 projection payload this adapter reads.

    Parsed from the caller-supplied serialized ``agent-os-compute-control-
    projection/1.0`` payload (e.g. via that schema's own
    ``serialize_compute_control_projection``). Fields this adapter never
    consults are intentionally not modeled here.
    """

    repository: str
    issue_number: int
    current_head_sha: str | None
    compute_disposition: str
    reason_codes: tuple[str, ...]


def parse_compute_control_projection_evidence(payload: object) -> ComputeControlProjectionEvidence:
    """Validate and narrow a caller-supplied #1419 projection payload.

    Raises ``ValueError`` for anything malformed, unsupported, or outside the
    frozen schema/vocabulary; callers treat that as a precheck failure.
    """

    if type(payload) is not dict:
        raise ValueError("projection payload must be an exact built-in mapping")
    if (
        payload.get("schema_name") != COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME
        or payload.get("schema_version") != COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION
    ):
        raise ValueError("unsupported compute-control projection schema")
    repository = payload.get("repository")
    if not _text(repository) or "/" not in repository:
        raise ValueError("repository must be an exact owner/name string")
    issue_number = payload.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    current_head_sha = payload.get("current_head_sha")
    if current_head_sha is not None and not _sha40(current_head_sha):
        raise ValueError("current_head_sha must be a lowercase 40-character SHA or null")
    compute_disposition = payload.get("compute_disposition")
    if compute_disposition not in COMPUTE_DECISION_PRESENTATION:
        raise ValueError("compute_disposition is outside the supported vocabulary")
    reason_codes = payload.get("reason_codes")
    if type(reason_codes) is not list or any(type(item) is not str for item in reason_codes):
        raise ValueError("reason_codes must be an exact built-in list of strings")
    return ComputeControlProjectionEvidence(
        repository=repository,
        issue_number=issue_number,
        current_head_sha=current_head_sha,
        compute_disposition=compute_disposition,
        reason_codes=tuple(reason_codes),
    )


@dataclass(frozen=True, slots=True)
class PropertyBinding:
    logical_field: str
    property_name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class NotionPropertySpec:
    name: str
    property_type: str


@dataclass(frozen=True, slots=True)
class NotionTaskPageEvidence:
    """One existing Notion Tasks / Issues row as read back by the caller's client.

    ``compute_decision`` is ``None`` when the property is currently empty.
    Any other existing property on the row is intentionally not modeled here:
    this writer only ever names ``Compute Decision`` in an update call, so
    every other property is left untouched by construction.
    """

    page_id: str
    source_link: str
    compute_decision: str | None


class NotionRateLimitError(Exception):
    def __init__(self, retry_after: float) -> None:
        if type(retry_after) not in {int, float}:
            raise TypeError("retry_after must be an exact number")
        delay = float(retry_after)
        if delay != delay or delay < 0 or delay > MAX_TOTAL_RETRY_DELAY:
            raise ValueError("retry_after is outside the supported range")
        super().__init__("notion request was rate limited")
        self.retry_after = delay


class NotionTransientError(Exception):
    """Client-neutral transient failure with no provider text exposure."""


class NotionComputeDecisionClient(Protocol):
    """Read/write shape this destination needs, mirroring the #959 NotionClient.

    A distinct, narrowly-scoped Protocol -- not a shared abstraction. No
    second Notion client implementation, credential path, or synchronization
    service is introduced; only the same proven dependency-injection shape is
    reused for this destination.
    """

    def fetch_schema(self, data_source_id: str) -> tuple[NotionPropertySpec, ...]: ...

    def find_exact(
        self, *, data_source_id: str, property_name: str, value: str
    ) -> tuple[NotionTaskPageEvidence, ...]: ...

    def update_page(self, *, page_id: str, properties: tuple[tuple[str, str], ...]) -> None: ...

    def fetch_page(self, page_id: str) -> NotionTaskPageEvidence | None: ...


@dataclass(frozen=True, slots=True)
class ComputeDecisionWriteRequest:
    data_source_id: str
    source_link: str
    source_link_property_name: str
    expected_identity: CanonicalIdentity
    projection: ComputeControlProjectionEvidence
    compute_decision_binding: PropertyBinding
    dry_run: bool = True
    maximum_retries: int = 2
    maximum_total_retry_delay: float = 30.0


@dataclass(frozen=True, slots=True)
class ComputeDecisionWriteResult:
    state: WriteState
    dry_run: bool
    page_id: str | None
    intended_value: str | None
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    authority_created: Literal[False] = field(default=False, init=False)


def plan_and_write_compute_decision(
    request: ComputeDecisionWriteRequest,
    client: NotionComputeDecisionClient | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> ComputeDecisionWriteResult:
    """Plan, and only when authorized/non-dry-run, apply one bounded update.

    Precedence is fail-closed and fixed: request validity, then projection
    currentness relative to the caller's expected identity, then exact
    Source-Link target resolution, then unchanged-skip, then update.
    """

    reason = _validate_request(request)
    if reason:
        return _result(request, WriteState.PRECHECK_FAILED, (reason,))

    stale_reason = _staleness_reason(request)
    if stale_reason:
        return _result(request, WriteState.PRECHECK_FAILED, (stale_reason,))

    intended_value = COMPUTE_DECISION_PRESENTATION[request.projection.compute_disposition]

    if request.dry_run:
        return _result(
            request, WriteState.DRY_RUN, ("notion-compute-decision-dry-run-valid",),
            intended_value=intended_value,
        )
    if client is None:
        return _result(
            request, WriteState.PRECHECK_FAILED, ("notion-compute-decision-client-required",),
            intended_value=intended_value,
        )

    schema_reason = _schema_preflight(client, request, sleep)
    if schema_reason:
        return _result(request, WriteState.PRECHECK_FAILED, (schema_reason,), intended_value=intended_value)

    try:
        candidates = _retry(
            lambda: client.find_exact(
                data_source_id=request.data_source_id,
                property_name=request.source_link_property_name,
                value=request.source_link,
            ),
            request,
            sleep,
        )
    except _RetryExhausted:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-target-retry-exhausted",),
            intended_value=intended_value,
        )
    except Exception:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-target-read-failed",),
            intended_value=intended_value,
        )

    exact = _exact_candidates(candidates, request.source_link)
    if exact is None:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-target-evidence-invalid",),
            intended_value=intended_value,
        )
    if not exact:
        return _result(
            request, WriteState.PRECHECK_FAILED, ("notion-compute-decision-target-missing",),
            intended_value=intended_value,
        )
    if len(exact) > 1:
        return _result(
            request, WriteState.PRECHECK_FAILED, ("notion-compute-decision-target-ambiguous",),
            intended_value=intended_value,
        )

    page = exact[0]
    if page.compute_decision == intended_value:
        return _verified(
            request, page.page_id, intended_value, WriteState.UNCHANGED_SKIP, False,
            ("notion-compute-decision-unchanged",),
        )

    intended_properties = ((request.compute_decision_binding.property_name, intended_value),)
    try:
        client.update_page(page_id=page.page_id, properties=intended_properties)
    except (NotionRateLimitError, NotionTransientError):
        return _reconcile_after_ambiguous_update(client, request, page, intended_value, sleep)
    except Exception:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-update-failed",),
            page_id=page.page_id, intended_value=intended_value, external=True,
        )

    try:
        readback = _retry(lambda: client.fetch_page(page.page_id), request, sleep)
    except _RetryExhausted:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-readback-retry-exhausted",),
            page_id=page.page_id, intended_value=intended_value, external=True,
        )
    except Exception:
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-readback-failed",),
            page_id=page.page_id, intended_value=intended_value, external=True,
        )

    if not _matches(readback, page.page_id, request.source_link, intended_value):
        return _result(
            request, WriteState.FAILED, ("notion-compute-decision-readback-mismatch",),
            page_id=page.page_id, intended_value=intended_value, external=True,
        )
    return _verified(
        request, page.page_id, intended_value, WriteState.UPDATED, True,
        ("notion-compute-decision-updated-verified",),
    )


def _reconcile_after_ambiguous_update(
    client: NotionComputeDecisionClient,
    request: ComputeDecisionWriteRequest,
    page: NotionTaskPageEvidence,
    intended_value: str,
    sleep: Callable[[float], None],
) -> ComputeDecisionWriteResult:
    """Reconcile an update whose outcome is unknown; never blindly retry the write."""

    try:
        readback = _retry(lambda: client.fetch_page(page.page_id), request, sleep)
    except Exception:
        readback = None
    if _matches(readback, page.page_id, request.source_link, intended_value):
        return _verified(
            request, page.page_id, intended_value, WriteState.UPDATED, True,
            ("notion-compute-decision-write-ambiguous-reconciled",),
        )
    return _result(
        request, WriteState.AMBIGUOUS_WRITE_RESULT, ("notion-compute-decision-update-outcome-ambiguous",),
        page_id=page.page_id, intended_value=intended_value, external=True,
    )


def _matches(
    readback: NotionTaskPageEvidence | None, page_id: str, source_link: str, intended_value: str
) -> bool:
    return (
        readback is not None
        and type(readback) is NotionTaskPageEvidence
        and readback.page_id == page_id
        and readback.source_link == source_link
        and readback.compute_decision == intended_value
    )


def _exact_candidates(
    candidates: object, source_link: str
) -> tuple[NotionTaskPageEvidence, ...] | None:
    """Filter to rows whose *exact* Source Link matches. Title is never consulted."""

    if type(candidates) is not tuple or any(type(c) is not NotionTaskPageEvidence for c in candidates):
        return None
    seen: dict[str, NotionTaskPageEvidence] = {}
    for candidate in candidates:
        if not _text(candidate.page_id):
            return None
        if candidate.page_id in seen and seen[candidate.page_id] != candidate:
            return None
        seen[candidate.page_id] = candidate
    return tuple(c for c in seen.values() if c.source_link == source_link)


def _validate_request(request: object) -> str | None:
    if type(request) is not ComputeDecisionWriteRequest:
        return "notion-compute-decision-invalid-request"
    if request.data_source_id != DATA_SOURCE_ID:
        return "notion-compute-decision-destination-mismatch"
    if not _text(request.source_link) or not _text(request.source_link_property_name):
        return "notion-compute-decision-identity-missing"
    if type(request.expected_identity) is not CanonicalIdentity:
        return "notion-compute-decision-identity-invalid"
    if type(request.projection) is not ComputeControlProjectionEvidence:
        return "notion-compute-decision-projection-invalid"
    if request.projection.compute_disposition not in COMPUTE_DECISION_PRESENTATION:
        return "notion-compute-decision-projection-invalid"
    if type(request.compute_decision_binding) is not PropertyBinding:
        return "notion-compute-decision-binding-invalid"
    binding = request.compute_decision_binding
    if (
        binding.logical_field not in WRITABLE_LOGICAL_FIELDS
        or not _text(binding.property_name)
        or binding.property_type != "rich_text"
    ):
        return "notion-compute-decision-field-not-allowlisted"
    if type(request.dry_run) is not bool:
        return "notion-compute-decision-invalid-request"
    if type(request.maximum_retries) is not int or request.maximum_retries < 0 or request.maximum_retries > MAX_RETRIES:
        return "notion-compute-decision-invalid-retry-policy"
    if type(request.maximum_total_retry_delay) not in {int, float}:
        return "notion-compute-decision-invalid-retry-policy"
    delay = float(request.maximum_total_retry_delay)
    if delay != delay or delay < 0 or delay > MAX_TOTAL_RETRY_DELAY:
        return "notion-compute-decision-invalid-retry-policy"
    return None


def _staleness_reason(request: ComputeDecisionWriteRequest) -> str | None:
    projection = request.projection
    expected = request.expected_identity
    if (
        projection.repository != expected.repository
        or projection.issue_number != expected.issue_number
        or projection.current_head_sha != expected.current_head_sha
    ):
        return "notion-compute-decision-identity-mismatch"
    if set(projection.reason_codes) & _STALE_PROJECTION_REASON_CODES:
        return "notion-compute-decision-projection-stale-or-conflicting"
    return None


def _schema_preflight(
    client: NotionComputeDecisionClient, request: ComputeDecisionWriteRequest, sleep: Callable[[float], None]
) -> str | None:
    try:
        schema = _retry(lambda: client.fetch_schema(request.data_source_id), request, sleep)
    except _RetryExhausted:
        return "notion-compute-decision-schema-retry-exhausted"
    except Exception:
        return "notion-compute-decision-schema-read-failed"
    if type(schema) is not tuple or any(type(spec) is not NotionPropertySpec for spec in schema):
        return "notion-compute-decision-schema-response-invalid"
    live: dict[str, str] = {}
    for spec in schema:
        if not _text(spec.name) or spec.name in live:
            return "notion-compute-decision-schema-response-invalid"
        live[spec.name] = spec.property_type
    binding = request.compute_decision_binding
    if binding.property_name not in live:
        return "notion-compute-decision-schema-property-missing"
    if live[binding.property_name] != binding.property_type:
        return "notion-compute-decision-schema-property-type-drift"
    return None


class _RetryExhausted(Exception):
    pass


def _retry(call: Callable[[], T], request: ComputeDecisionWriteRequest, sleep: Callable[[float], None]) -> T:
    retries = 0
    total_delay = 0.0
    while True:
        try:
            return call()
        except NotionRateLimitError as error:
            delay = error.retry_after
        except NotionTransientError:
            delay = 0.0
        if retries >= request.maximum_retries or total_delay + delay > float(request.maximum_total_retry_delay):
            raise _RetryExhausted from None
        if delay:
            sleep(delay)
        total_delay += delay
        retries += 1


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= MAX_TEXT


def _sha40(value: object) -> bool:
    return type(value) is str and bool(_SHA40_RE.fullmatch(value))


def _result(
    request: object,
    state: WriteState,
    reasons: tuple[str, ...],
    *,
    page_id: str | None = None,
    intended_value: str | None = None,
    external: bool = False,
) -> ComputeDecisionWriteResult:
    dry = request.dry_run if type(request) is ComputeDecisionWriteRequest and type(request.dry_run) is bool else True
    return ComputeDecisionWriteResult(state, dry, page_id, intended_value, reasons, False, external)


def _verified(
    request: ComputeDecisionWriteRequest,
    page_id: str,
    intended_value: str,
    state: WriteState,
    external: bool,
    reasons: tuple[str, ...],
) -> ComputeDecisionWriteResult:
    return ComputeDecisionWriteResult(state, request.dry_run, page_id, intended_value, reasons, True, external)
