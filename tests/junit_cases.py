"""Collect each unittest table row as a test, independent of JUnit internals."""
from functools import partialmethod


def collect_cases(test_class, check, cases):
    """Register one test method per row on this class.

    Suffixes use at least two digits. Once a table reaches 100 rows, lexical
    order is not numeric; tests must not rely on execution order. Registering
    the same names twice on one class raises instead of replacing tests.
    A normal re-import that creates a fresh class is independent.
    """
    name = check.__name__.removeprefix("_check_")
    for index, arguments in enumerate(cases, start=1):
        test_name = f"test_{name}_{index:02}"
        if hasattr(test_class, test_name):
            raise ValueError(f"duplicate test case: {test_name}")
        setattr(test_class, test_name, partialmethod(check, *arguments))
