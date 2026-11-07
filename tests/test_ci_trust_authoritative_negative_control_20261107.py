"""Disposable CI trust negative control: intentionally fail on Ready PR.

Never merge. Used only to prove authoritative aggregate and branch rules fail closed.
"""

def test_authoritative_aggregate_cannot_succeed_with_failing_pytest():
    assert False, "CI_TRUST_AUDIT_EXPECTED_FAILURE_20261107"
