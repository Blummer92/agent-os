"""Connector-facing diagnostic for pre-job workflow-definition failures (#3272).

The #3277 classifier (``classify_workflow_run_evidence`` in
``scripts/agent_os_issue_acceptance/zero_job_validation_recovery.py``) already
distinguishes a ``completed``/``failure`` run with zero jobs
(``ZeroJobRunDisposition.PRE_JOB_FAILURE``) from pending/currentness shapes and
from ordinary executed failures. This module does not reimplement that
classification. It consumes the classifier's result and renders bounded,
actionable, connector-facing evidence for the one shape the GitHub connector
previously left undiagnosed: a workflow run that failed before any job
executed.

For ``PRE_JOB_FAILURE`` the diagnostic states only what the run metadata
proves (workflow-definition/pre-job rejection, zero jobs executed,
re-dispatch cannot clear it), explicitly names what is not proven (GitHub's
workflow parser diagnostic is never inferred from run metadata), and
recommends the single bounded next action (inspect the workflow revision
locally; do not treat the shape as a candidate code-test failure).

Pending + zero-jobs shapes are delegated to the #3269 validation-gate
currentness path, never duplicated here. Ordinary executed failures are
reported as ordinary test failures.

This module is a pure decision function in the established seam pattern
(#1237 ``post_selection_continuation.py``, #3139, #3269). It performs no
network I/O, reads no live GitHub state, grants no merge/closure/branch/
workflow authority, and creates no parser, router, manager, scheduler,
recovery framework, poller, daemon, or cache.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    WorkflowRunConclusionEvidence,
    ZeroJobRunDisposition,
)

ZERO_JOB_DIAGNOSTIC_SCHEMA_NAME = "agent-os-zero-job-definition-diagnostic"
ZERO_JOB_DIAGNOSTIC_SCHEMA_VERSION = "1.0"

MAX_DIAGNOSTIC_REASON_CODES = 16
MAX_DIAGNOSTIC_STATEMENTS = 8
MAX_DIAGNOSTIC_STATEMENT_LENGTH = 512
MAX_DIAGNOSTIC_ACTION_LENGTH = 1024
MAX_DIAGNOSTIC_SERIALIZED_BYTES = 16384


class ZeroJobDiagnosticKind(str, Enum):
    """The single deterministic diagnostic verdict for the observed shape."""

    #: completed/failure with zero jobs: a workflow-definition/pre-job
    #: rejection. No job executed, so no test code ran.
    PRE_JOB_DEFINITION_REJECTION = "pre-job-definition-rejection"
    #: pending + zero jobs: belongs to the #3269 validation-gate currentness
    #: path. This diagnostic delegates and duplicates nothing.
    CURRENTNESS_DELEGATED = "currentness-delegated"
    #: one or more jobs executed and the run failed: an ordinary candidate
    #: test failure.
    ORDINARY_TEST_FAILURE = "ordinary-test-failure"
    #: the evidence does not determine a definition rejection. Fail-closed:
    #: no repair action is emitted and the caller keeps its behavior.
    INDETERMINATE = "indeterminate"


class ZeroJobDiagnosticReason(str, Enum):
    """Finite reason codes explaining one deterministic diagnostic."""

    #: the completed/failure + zero-jobs shape is present in the evidence.
    PRE_JOB_FAILURE_PROVEN = "diagnostic.pre-job-failure-proven"
    #: re-dispatching the identical workflow revision cannot clear a
    #: definition rejection.
    REDISPATCH_CANNOT_CLEAR = "diagnostic.redispatch-cannot-clear"
    #: GitHub's workflow parser diagnostic is not in run metadata and is
    #: never inferred by this module.
    PARSER_DIAGNOSTIC_NOT_PROVEN = "diagnostic.parser-diagnostic-not-proven"
    #: the bounded next action is local inspection of the workflow revision.
    INSPECT_WORKFLOW_REVISION = "diagnostic.inspect-workflow-revision"
    #: the shape was delegated to the #3269 currentness cross-check path.
    DELEGATED_TO_CURRENTNESS_PATH = "diagnostic.delegated-to-currentness-path"
    #: at least one job executed with a failure conclusion.
    EXECUTED_FAILURE_OBSERVED = "diagnostic.executed-failure-observed"
    #: the evidence is insufficient for a definition-rejection verdict.
    INSUFFICIENT_EVIDENCE = "diagnostic.insufficient-evidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class ZeroJobDiagnosticInput:
    """Caller-supplied classification result plus the classified evidence."""

    disposition: ZeroJobRunDisposition
    runs: tuple[WorkflowRunConclusionEvidence, ...]
    workflow_path: str | None = None
    workflow_name: str | None = None

    def __post_init__(self) -> None:
        if type(self.disposition) is not ZeroJobRunDisposition:
            raise TypeError("disposition must be an exact ZeroJobRunDisposition")
        if type(self.runs) is not tuple or any(
            type(run) is not WorkflowRunConclusionEvidence for run in self.runs
        ):
            raise TypeError(
                "runs must be an exact tuple of WorkflowRunConclusionEvidence values"
            )
        if (
            self.disposition is ZeroJobRunDisposition.PRE_JOB_FAILURE
            and not self.runs
        ):
            raise ValueError(
                "a pre-job-failure disposition requires at least one run"
            )
        for name in ("workflow_path", "workflow_name"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class ZeroJobDefinitionDiagnostic:
    """Bounded connector-facing evidence for one classified zero-job shape."""

    kind: ZeroJobDiagnosticKind
    proven: tuple[str, ...]
    not_proven: tuple[str, ...]
    recommended_action: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.kind) is not ZeroJobDiagnosticKind:
            raise TypeError("kind must be an exact ZeroJobDiagnosticKind")
        for name in ("proven", "not_proven"):
            value = getattr(self, name)
            if (
                type(value) is not tuple
                or len(value) > MAX_DIAGNOSTIC_STATEMENTS
                or any(
                    type(statement) is not str
                    or not statement.strip()
                    or len(statement) > MAX_DIAGNOSTIC_STATEMENT_LENGTH
                    for statement in value
                )
            ):
                raise TypeError(
                    f"{name} must be a tuple of at most "
                    f"{MAX_DIAGNOSTIC_STATEMENTS} non-empty statements"
                )
        if type(self.recommended_action) is not str or len(
            self.recommended_action
        ) > MAX_DIAGNOSTIC_ACTION_LENGTH:
            raise TypeError("recommended_action must be a string within the length bound")
        if (
            type(self.reason_codes) is not tuple
            or not self.reason_codes
            or len(self.reason_codes) > MAX_DIAGNOSTIC_REASON_CODES
            or any(type(code) is not str or not code for code in self.reason_codes)
        ):
            raise TypeError(
                "reason_codes must be a non-empty tuple of non-empty strings"
            )
        if self.kind is ZeroJobDiagnosticKind.INDETERMINATE and self.recommended_action:
            raise ValueError(
                "an indeterminate diagnostic must not recommend an action"
            )


def _pre_job_rejection(input: ZeroJobDiagnosticInput) -> ZeroJobDefinitionDiagnostic:
    location = (
        f" at {input.workflow_path}" if input.workflow_path is not None else ""
    )
    return ZeroJobDefinitionDiagnostic(
        kind=ZeroJobDiagnosticKind.PRE_JOB_DEFINITION_REJECTION,
        proven=(
            "the workflow run completed with conclusion 'failure' and zero jobs executed",
            "no test code ran: the failure occurred before any job started",
            "re-dispatching the identical workflow revision cannot clear this shape",
        ),
        not_proven=(
            "GitHub's workflow parser diagnostic is not present in run metadata "
            "and is never inferred",
            "the specific invalid workflow syntax is not proven by this evidence",
        ),
        recommended_action=(
            f"inspect the workflow revision locally{location} and correct the "
            "workflow definition; do not treat this as a candidate code-test "
            "failure and do not re-dispatch the identical revision"
        ),
        reason_codes=(
            ZeroJobDiagnosticReason.PRE_JOB_FAILURE_PROVEN.value,
            ZeroJobDiagnosticReason.REDISPATCH_CANNOT_CLEAR.value,
            ZeroJobDiagnosticReason.PARSER_DIAGNOSTIC_NOT_PROVEN.value,
            ZeroJobDiagnosticReason.INSPECT_WORKFLOW_REVISION.value,
        ),
    )


def _currentness_delegated() -> ZeroJobDefinitionDiagnostic:
    return ZeroJobDefinitionDiagnostic(
        kind=ZeroJobDiagnosticKind.CURRENTNESS_DELEGATED,
        proven=("the workflow run was observed with zero jobs and no terminal conclusion",),
        not_proven=("whether the connector wrapper snapshot is current",),
        recommended_action=(
            "delegate to the #3269 validation-gate currentness path: obtain "
            "canonical check-run evidence for the head SHA before presenting "
            "state; this diagnostic duplicates no currentness logic"
        ),
        reason_codes=(
            ZeroJobDiagnosticReason.DELEGATED_TO_CURRENTNESS_PATH.value,
        ),
    )


def _ordinary_test_failure() -> ZeroJobDefinitionDiagnostic:
    return ZeroJobDefinitionDiagnostic(
        kind=ZeroJobDiagnosticKind.ORDINARY_TEST_FAILURE,
        proven=("at least one job executed and the run concluded with failure",),
        not_proven=("which specific test failed: see the executed job logs",),
        recommended_action=(
            "investigate the failed jobs as an ordinary candidate test failure"
        ),
        reason_codes=(
            ZeroJobDiagnosticReason.EXECUTED_FAILURE_OBSERVED.value,
        ),
    )


def _indeterminate() -> ZeroJobDefinitionDiagnostic:
    return ZeroJobDefinitionDiagnostic(
        kind=ZeroJobDiagnosticKind.INDETERMINATE,
        proven=(),
        not_proven=("the evidence does not determine a workflow-definition rejection",),
        recommended_action="",
        reason_codes=(ZeroJobDiagnosticReason.INSUFFICIENT_EVIDENCE.value,),
    )


def diagnose_zero_job_run(
    diagnostic_input: ZeroJobDiagnosticInput,
) -> ZeroJobDefinitionDiagnostic:
    """Render bounded connector-facing evidence for one classified shape.

    The classification itself comes from
    ``classify_workflow_run_evidence``; this function never re-decides
    precedence and never infers evidence the run metadata does not contain.
    Shapes outside the three governed verdicts fail closed to
    ``INDETERMINATE`` with no recommended action.
    """
    if type(diagnostic_input) is not ZeroJobDiagnosticInput:
        raise TypeError("diagnostic_input must be an exact ZeroJobDiagnosticInput")
    disposition = diagnostic_input.disposition
    if disposition is ZeroJobRunDisposition.PRE_JOB_FAILURE:
        return _pre_job_rejection(diagnostic_input)
    if disposition is ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED:
        return _currentness_delegated()
    if disposition is ZeroJobRunDisposition.REAL_FAILURE:
        return _ordinary_test_failure()
    return _indeterminate()


def serialize_zero_job_definition_diagnostic(
    diagnostic: ZeroJobDefinitionDiagnostic,
) -> str:
    """Deterministic JSON serialization for evidence bundles."""
    if type(diagnostic) is not ZeroJobDefinitionDiagnostic:
        raise TypeError(
            "diagnostic must be an exact ZeroJobDefinitionDiagnostic"
        )
    payload = {
        "schema": ZERO_JOB_DIAGNOSTIC_SCHEMA_NAME,
        "schema_version": ZERO_JOB_DIAGNOSTIC_SCHEMA_VERSION,
        "kind": diagnostic.kind.value,
        "proven": list(diagnostic.proven),
        "not_proven": list(diagnostic.not_proven),
        "recommended_action": diagnostic.recommended_action,
        "reason_codes": list(diagnostic.reason_codes),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_DIAGNOSTIC_SERIALIZED_BYTES:
        raise ValueError("serialized diagnostic exceeds the byte bound")
    return serialized
