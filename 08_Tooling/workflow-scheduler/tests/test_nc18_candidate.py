"""Wave 3 NC18 candidate: a dict codespaces container must never select a surface.

Local-only candidate. Intended home (when filed): the existing test file
08_Tooling/workflow-scheduler/tests/test_mutation_codespace_resolver_invalid_container.py.

Provenance: Wave 2 PR #3851's test (codespaces=None) kills its mutant by
crash, and the NC17 candidate (FU-RESOLVER-1, empty dict + total 0) kills the
unconditional dict->values coercion mutant by wrong reason. But neither
detects a coercion that only fires on a *non-empty* dict: with
{"total_count": 1, "codespaces": {"fabricated": <qualified Available entry>}}
such a mutant selects the fabricated surface (proven by probe: selected=True,
reason "codespaces-capable", name "fabricated-codespace") while both existing
detectors still pass. This case asserts the refusal/no-selection boundary
directly on that input, so it kills both the unconditional and the
non-empty-only coercion mutants for the intended reason (a selection that
must not exist).

Note: {"total_count": 1, "codespaces": {}} is deliberately NOT asserted
here -- it refuses identically on clean and on both coercion mutants
(length mismatch), so it cannot discriminate and would be a dead test.
"""
import json
import subprocess

import pytest

from workflow_scheduler.governance.dev_validation_codespaces import (
    resolve_current_codespace,
)

FABRICATED_ENTRY = {
    "name": "fabricated-codespace",
    "state": "Available",
    "repository": {"full_name": "Blummer92/agent-os"},
    "owner": {"login": "Blummer92"},
}


def test_resolver_dict_container_with_fabricated_entry_never_selects(monkeypatch):
    """A dict codespaces container is refused; no fabricated surface selected.

    The dict holds one fully qualified, Available entry -- exactly the input
    a dict->values coercion would turn into a selection. Clean behavior is
    a refusal with the exact invalid-container reason, no selection, no
    surface name, exactly one provider read, and no exception.
    """
    monkeypatch.setenv("GH_TOKEN", "test-read-token")
    calls = []

    def fake_run(argv, *, timeout):
        calls.append((tuple(argv), timeout))
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {"total_count": 1, "codespaces": {"fabricated": FABRICATED_ENTRY}}
            ),
            "",
        )

    try:
        selection = resolve_current_codespace(fake_run)
    except TypeError as exc:
        pytest.fail(f"clean refusal required, got TypeError: {exc!r}")

    assert selection.selected is False
    assert selection.reason == "codespaces-read-evidence-invalid"
    assert selection.codespace_name is None
    assert len(calls) == 1
