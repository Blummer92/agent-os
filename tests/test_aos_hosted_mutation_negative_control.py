"""Disposable hosted CI negative control. Never merge this test."""

def test_deliberate_ci_failure_must_reach_authoritative_gate():
    assert False, "AOS-HOSTED-MUT-NC: intentional pytest failure"
