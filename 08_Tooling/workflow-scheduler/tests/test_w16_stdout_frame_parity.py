"""Keep each transport's stdout frame and failure reasons lane-local."""

from __future__ import annotations

from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from workflow_scheduler.governance import (
    codespaces_diagnostic as diagnostic,
    dev_validation_codespaces as codespaces,
    dev_validation_gce as gce,
    discovery_codespaces as discovery,
)
from workflow_scheduler.governance.dev_validation import (
    REPOSITORY,
    VALIDATION_ID,
    build_dev_validation_request,
)

_LANES = (
    ("codespaces", codespaces, "dev-validation-codespaces"),
    ("discovery", discovery, "discovery-codespaces"),
    ("diagnostic", diagnostic, "codespaces-diagnostic"),
    ("gce", gce, "dev-validation"),
)


@pytest.mark.parametrize(("lane", "module", "reason_prefix"), _LANES, ids=[row[0] for row in _LANES])
@pytest.mark.parametrize(
    "shape",
    ("unframed", "reversed", "repeated-start", "repeated-end", "foreign-1",
     "foreign-2", "foreign-3", "empty", "malformed", "json-list", "json-object"),
)
def test_transport_preserves_frame_isolation_and_own_failure_reason(lane, module, reason_prefix, shape):
    start, end = module._FRAME_START, module._FRAME_END
    if shape.startswith("foreign-"):
        other = [candidate for name, candidate, _ in _LANES if name != lane][int(shape[-1]) - 1]
        stdout = other._FRAME_START + "{}" + other._FRAME_END
    else:
        stdout = {
            "unframed": "{}",
            "reversed": end + "{}" + start,
            "repeated-start": start * 2 + "{}" + end,
            "repeated-end": start + "{}" + end * 2,
            "empty": start + end,
            "malformed": start + "not JSON" + end,
            "json-list": start + "[]" + end,
            "json-object": "runner banner\n" + start + "\n {} \n" + end + "\nrunner trailer",
        }[shape]

    def run(argv, *, timeout):
        return CompletedProcess(argv, 0, stdout=stdout, stderr="")

    if lane in {"codespaces", "gce"}:
        request = build_dev_validation_request(
            repository=REPOSITORY, issue_number=3690, branch="agent/3690-frame-parity",
            source_sha="a" * 40, validation_id=VALIDATION_ID,
        )
        if lane == "codespaces":
            result = codespaces.run_dev_validation_over_codespaces(
                request, codespace_name="fluffy-current-agentos-7x9q", run=run
            )
        else:
            adapter = SimpleNamespace(_ssh=lambda resource, command, *, timeout: run(command, timeout=timeout))
            result = gce.run_dev_validation_over_ssh(adapter, request)
    elif lane == "diagnostic":
        request = diagnostic.CodespacesDiagnosticRequest(
            repository=REPOSITORY, issue_number=3690, diagnostic_id=diagnostic.DIAGNOSTIC_ID,
            request_id="w16-frame-parity",
        )
        result = diagnostic.run_codespaces_diagnostic(
            request, codespace_name="fluffy-current-agentos-7x9q", run=run
        )
    else:
        result = discovery.run_discovery_over_codespaces(
            discovery.DiscoveryRequest(repository=REPOSITORY, issue_number=3690),
            codespace_name="fluffy-current-agentos-7x9q", run=run,
        )["discovery"]

    suffix = {
        "empty": "evidence-not-json",
        "malformed": "evidence-not-json",
        "json-list": "evidence-malformed",
        "json-object": "identity-mismatch" if lane == "discovery" else "evidence-identity-mismatch",
    }.get(shape, "frame-invalid")
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == [f"{reason_prefix}-{suffix}"]
    assert result["execution_authorized"] is False
