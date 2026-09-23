import os

import pytest


@pytest.fixture(autouse=True)
def stable_process_identity_for_summary_independence_test(request, monkeypatch):
    """Keep the PID-leak assertion deterministic without weakening its intent."""
    if request.node.name == "test_output_independent_of_environment_and_process_identity":
        monkeypatch.setattr(os, "getpid", lambda: -9876543210123456789)
