"""NC09 disposable hosted negative control. Intentionally failing. NEVER MERGE."""


def test_nc09_swallowed_exit_must_not_hide_failing_junit():
    assert False, "NC09_DISPOSABLE_FAILURE_20261115"
