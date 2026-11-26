"""Serialize results and safe error envelopes; no input acquisition or metric logic."""

import json
from datetime import date, datetime
from enum import Enum

from .errors import ValidationError


def _json_type(value):
    """Return an enum value or ISO datetime; reject unsupported objects."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError("Unsupported report value.")


def render(payload):
    """Serialize fully before writing so a failure cannot emit partial JSON."""
    try:
        return json.dumps(payload, indent=2, allow_nan=False, default=_json_type)
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("report_encoding", "Report contains unsupported values.", "report") from None


def error_payload(error):
    """Turn a structured error into one bounded CLI JSON object."""
    return {"error": {"code": error.code, "message": error.message, "field": error.field, **error.details}}
