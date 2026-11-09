"""NC09 hosted negative control. Disposable test: NEVER MERGE."""


def test_nc09_disposable_failing_body() -> None:
    """Produce a real failed JUnit testcase; runner mutation swallows exit 1."""
    assert False, "NC09 intentional hosted negative control: failing pytest body"
