"""Resolver mutmut_1: wrong JSON container type is a denial, not a crash."""
import json
import subprocess
from workflow_scheduler.governance.dev_validation_codespaces import resolve_current_codespace


def test_resolver_nonlist_codespaces_container_refuses_before_length_or_iteration(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "test-read-token")
    calls = []
    def fake_run(argv, *, timeout):
        calls.append((tuple(argv), timeout))
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            "total_count": 1, "codespaces": None,
        }), "")
    selection = resolve_current_codespace(fake_run)
    assert selection.selected is False
    assert selection.reason == "codespaces-read-evidence-invalid"
    assert len(calls) == 1
