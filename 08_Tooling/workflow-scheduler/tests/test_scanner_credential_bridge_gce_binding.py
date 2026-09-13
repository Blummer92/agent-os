from __future__ import annotations

import workflow_scheduler.governance.dev_validation_gce as live


def test_scanner_host_runner_binds_only_fixed_host_bridge():
    source = live._HOST_RUNNER_SOURCE
    assert 'SCANNER_PROOF_ID="issue-scanner-proof"' in source
    assert 'SCANNER_PROOF_HOST_MODULE="scripts.agent_os_github_issue_provider.scanner_proof_host_bridge"' in source
    assert "scanner-proof-credential-injector-unavailable" not in source
    assert "SECRET_RESOURCE" not in source
    assert "VALIDATOR_PRINCIPAL" not in source
    assert "private_key" not in source
    assert "Authorization" not in source
    assert "GITHUB_TOKEN" not in source


def test_scanner_host_runner_keeps_fixed_no_argument_invocation():
    source = live._HOST_RUNNER_SOURCE
    assert "(HOST_PYTHON,\"-m\",SCANNER_PROOF_HOST_MODULE)" in source
    assert "record_scanner_proof" in source
    assert "*test_args" not in source[source.index('elif validation_id==SCANNER_PROOF_ID:'):source.index('elif validation_id==SHEETS_SMOKE_ID:')]


def test_scanner_host_runner_source_compiles():
    compile(live._HOST_RUNNER_SOURCE, "<agent-os-dev-validation-host>", "exec")
