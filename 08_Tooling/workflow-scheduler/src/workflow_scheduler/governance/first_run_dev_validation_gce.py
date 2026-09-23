"""Observed wrapper around the existing fixed GCE dev-validation runner for #1972.

The wrapper does not define validation commands. It executes the exact argv already
constructed by ``dev_validation_gce`` on the same host, records host-observed UTC
start/completion instants, and augments only the returned bounded evidence. It
creates no caller-selectable command surface and remains non-authorizing.
"""
from __future__ import annotations

import json
import shlex

from .dev_validation import DevValidationRequest
from .dev_validation_gce import (
    HOST_PYTHON,
    _FRAME_END,
    _FRAME_START,
    _extract_framed_payload,
    _failure,
    _host_command,
)
from .first_run_validation_observation import FIXED_GCE_RUNNER_ID
from .gce_gcloud_adapter import GcloudIapAdapter, RESOURCE

_OBSERVED_FRAME_START = "===AGENT-OS-FIRST-RUN-DEV-VALIDATION-JSON-BEGIN==="
_OBSERVED_FRAME_END = "===AGENT-OS-FIRST-RUN-DEV-VALIDATION-JSON-END==="

_HOST_OBSERVER_SOURCE = r'''import datetime,json,subprocess,sys
START="===AGENT-OS-DEV-VALIDATION-JSON-BEGIN==="
END="===AGENT-OS-DEV-VALIDATION-JSON-END==="
OUT_START="===AGENT-OS-FIRST-RUN-DEV-VALIDATION-JSON-BEGIN==="
OUT_END="===AGENT-OS-FIRST-RUN-DEV-VALIDATION-JSON-END==="
RUNNER="agent-os-gce-dev-validation-v1"
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
started=now()
completed=subprocess.run(sys.argv[1:],check=False,capture_output=True,text=True)
finished=now()
stdout=completed.stdout
if completed.returncode!=0 or stdout.count(START)!=1 or stdout.count(END)!=1:
 raise SystemExit(64)
left=stdout.find(START)+len(START);right=stdout.find(END)
payload=json.loads(stdout[left:right].strip())
if not isinstance(payload,dict):raise SystemExit(64)
payload["runner_id"]=RUNNER;payload["started_at"]=started;payload["completed_at"]=finished
print(OUT_START);print(json.dumps(payload,sort_keys=True,separators=(",",":")));print(OUT_END)
'''


def _observed_host_command(request: DevValidationRequest) -> str:
    """Wrap only the exact existing fixed runner argv; no caller command input exists."""
    fixed_argv = tuple(shlex.split(_host_command(request)))
    if len(fixed_argv) < 3 or fixed_argv[0] != HOST_PYTHON or fixed_argv[1] != "-c":
        raise ValueError("fixed dev-validation host command drifted")
    return shlex.join((HOST_PYTHON, "-c", _HOST_OBSERVER_SOURCE, *fixed_argv))


def run_observed_dev_validation_over_ssh(
    adapter: GcloudIapAdapter, request: DevValidationRequest
) -> dict[str, object]:
    """Run the existing fixed runner once and require observed timing/runner evidence."""
    completed = adapter._ssh(RESOURCE, _observed_host_command(request))
    if completed.returncode != 0:
        return _failure(request, "first-run-dev-validation-ssh-failed")
    stdout = completed.stdout
    if type(stdout) is not str or stdout.count(_OBSERVED_FRAME_START) != 1 or stdout.count(_OBSERVED_FRAME_END) != 1:
        return _failure(request, "first-run-dev-validation-frame-invalid")
    left = stdout.find(_OBSERVED_FRAME_START) + len(_OBSERVED_FRAME_START)
    right = stdout.find(_OBSERVED_FRAME_END)
    try:
        payload = json.loads(stdout[left:right].strip())
    except json.JSONDecodeError:
        return _failure(request, "first-run-dev-validation-evidence-not-json")
    if type(payload) is not dict:
        return _failure(request, "first-run-dev-validation-evidence-malformed")
    fixed = {
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "validation_id": request.validation_id,
        "request_id": request.request_id,
        "runner_id": FIXED_GCE_RUNNER_ID,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        return _failure(request, "first-run-dev-validation-evidence-identity-mismatch")
    if type(payload.get("started_at")) is not str or type(payload.get("completed_at")) is not str:
        return _failure(request, "first-run-dev-validation-timing-missing")
    return payload


__all__ = ["run_observed_dev_validation_over_ssh"]
