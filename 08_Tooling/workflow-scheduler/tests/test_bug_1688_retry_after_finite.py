"""Regression coverage for #1688."""

import math

from workflow_scheduler.adapters.notion_readonly_adapter import _retry_after_seconds


class Headers:
    def __init__(self, value):
        self.value = value

    def get(self, name):
        assert name == "Retry-After"
        return self.value


def test_retry_after_rejects_positive_infinity():
    assert _retry_after_seconds(Headers("Infinity")) is None


def test_retry_after_keeps_finite_nonnegative_seconds():
    value = _retry_after_seconds(Headers("2.5"))
    assert value == 2.5
    assert math.isfinite(value)
