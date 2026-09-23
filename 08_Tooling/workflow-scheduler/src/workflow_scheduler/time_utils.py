"""UTC timestamp helpers for runtime and legacy persistence boundaries."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize aware or legacy naive UTC values to aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_storage_string(value: datetime) -> str:
    """Serialize UTC while preserving the legacy offset-free ISO format."""
    return ensure_utc(value).replace(tzinfo=None).isoformat()


def parse_utc_storage(value: str) -> datetime:
    """Parse legacy or offset-bearing ISO text as an aware UTC datetime."""
    return ensure_utc(datetime.fromisoformat(value))
