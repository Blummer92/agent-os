"""Structured reliability failures; no transport, input parsing, or reporting I/O."""

class ReliabilityError(RuntimeError):
    """Carry a stable code, safe message, field, and optional provider metadata."""

    def __init__(self, code, message, field, **details):
        super().__init__(message)
        self.code, self.message, self.field, self.details = code, message, field, details


class ValidationError(ReliabilityError, TypeError):
    """Invalid caller or record input; also compatible with the old TypeError API."""


class ReadError(ReliabilityError):
    """Failed or incomplete read-only acquisition."""
