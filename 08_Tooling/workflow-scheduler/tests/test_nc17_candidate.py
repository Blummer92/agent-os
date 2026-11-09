"""Wave 3 NC17 candidate (FU-RESOLVER-1): empty-dict container, zero total.

Local-only candidate. Intended home (when filed): the existing test file
08_Tooling/workflow-scheduler/tests/test_mutation_codespace_resolver_invalid_container.py.

Provenance: Wave 2 PR #3851's test kills its container-validation mutant by
crash (TypeError: len(None) on codespaces=None). A probe showed the same mutant
is *silently* wrong on a second input -- {"total_count": 0, "codespaces": {}}
returns the wrong reason "codespaces-no-qualified-surface" with no crash.
This case asserts a clean refusal with the exact invalid-container reason,
so the mutant must fail on the wrong reason, with no TypeError involved.
"""
import json
import subprocess

import pytest

from workflow_scheduler.governance.dev_validation_codespaces import (
    resolve_current_codespace,
)


def test_resolver_empty_dict_container_zero_total_refuses_with_invalid_container_reason(monkeypatch):
    """{total_count: 0, codespaces: {}} is a clean invalid-container refusal.

    No selection, exact reason "codespaces-read-evidence-invalid" (not
    "codespaces-no-qualified-surface"), exactly one provider read, and no
    exception of any kind -- in particular no TypeError.
    """
    monkeypatch.setenv("GH_TOKEN", "test-read-token")
    calls = []

    def fake_run(argv, *, timeout):
        calls.append((tuple(argv), timeout))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"total_count": 0, "codespaces": {}}), ""
        )

    try:
        selection = resolve_current_codespace(fake_run)
    except TypeError as exc:
        pytest.fail(f"clean refusal required, got TypeError: {exc!r}")

    assert selection.selected is False
    assert selection.reason == "codespaces-read-evidence-invalid"
    assert selection.codespace_name is None
    assert len(calls) == 1
