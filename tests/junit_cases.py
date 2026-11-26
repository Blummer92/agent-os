"""Collect each unittest table row as a test, independent of JUnit internals."""
from functools import partialmethod


def collect_cases(test_class, check, cases):
    name = check.__name__.removeprefix("_check_")
    for index, arguments in enumerate(cases, start=1):
        test_name = f"test_{name}_{index:02}"
        if hasattr(test_class, test_name):
            raise ValueError(f"duplicate test case: {test_name}")
        setattr(test_class, test_name, partialmethod(check, *arguments))
