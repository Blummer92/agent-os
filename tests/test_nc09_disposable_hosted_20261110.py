"""DISPOSABLE HOSTED CI NEGATIVE CONTROL: intentionally failing. NEVER MERGE.

Exact-head NC09 repair certification only. See PR #3859.
The test must fail in real pytest and leave a failing testcase in root JUnit.
"""


def test_nc09_swallowed_pytest_failure_is_rejected_by_junit_oracle():
    assert False, "NC09_DISPOSABLE_HOSTED_CANARY_FAILURE_20261110"
