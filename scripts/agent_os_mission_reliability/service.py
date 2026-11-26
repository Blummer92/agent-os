"""Compose acquisition and pure derivation; no CLI, HTTP transport, or output I/O."""

from collections.abc import Mapping

from .derive import derive_mission_reliability
from .errors import ReadError
from .github_source import acquire_frozen_records


def _record_numbers(records):
    """Extract exact int identities, never allowing bool-to-int equality."""
    if not isinstance(records, list):
        return None
    ids = [item.get("issue_number") if isinstance(item, Mapping) else None for item in records]
    return tuple(ids) if all(type(value) is int for value in ids) else None


def measure(read_json, population):
    """Build one report only when both acquisition identities match the frozen input."""
    frozen = acquire_frozen_records(read_json, population)
    records = frozen.get("records")
    metadata = frozen.get("frozen_issue_numbers")
    if frozen.get("repository") != population.repository or (
        type(metadata) is not list or any(type(n) is not int for n in metadata)
        or tuple(metadata) != population.issues or _record_numbers(records) != population.issues
    ):
        raise ReadError("incomplete_population", "Acquired records do not match the frozen population.", "issues")
    label = f"{population.repository} frozen issues {','.join(map(str, population.issues))}"
    report = derive_mission_reliability(records, window=label)
    report["window"] = {"repository": population.repository, "issue_numbers": list(population.issues), "label": label}
    return {"records": frozen, "report": report}
