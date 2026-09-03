"""CKR12 deterministic Lessons Learned activation accountability."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

ACTIVATION_CLASSES = frozenset({
    "signal-activatable",
    "known-reference-only",
    "context-only",
    "out-of-coding-scope",
})

ACTIVATION_READINESS = frozenset({
    "ready",
    "blocked-provenance",
    "blocked-vocabulary",
    "blocked-currentness",
    "blocked-conflict",
    "manual-review",
})

CATALOG_PATH = (
    Path(__file__).with_name("data")
    / "lesson_activation_accountability.json"
)


class LessonAccountabilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LessonActivationAccountability:
    lesson_id: str
    activation_class: str
    activation_readiness: str

    def __post_init__(self):
        if not self.lesson_id.strip():
            raise LessonAccountabilityError("lesson_id must be non-empty")
        if self.activation_class not in ACTIVATION_CLASSES:
            raise LessonAccountabilityError("unknown activation_class")
        if self.activation_readiness not in ACTIVATION_READINESS:
            raise LessonAccountabilityError("unknown activation_readiness")


def load_lesson_accountability_catalog(path=None):
    raw = json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise LessonAccountabilityError("catalog root must be a list")

    result = []
    seen = set()

    for item in raw:
        entry = LessonActivationAccountability(**item)
        if entry.lesson_id in seen:
            raise LessonAccountabilityError(
                f"duplicate lesson identity: {entry.lesson_id}"
            )
        seen.add(entry.lesson_id)
        result.append(entry)

    return tuple(result)


def compare_live_eligible_identities(catalog, live_lesson_ids: Iterable[str]):
    catalog_ids = {entry.lesson_id for entry in catalog}
    live = [str(value).strip() for value in live_lesson_ids]
    live_ids = set(live)

    return {
        "missing": tuple(sorted(live_ids - catalog_ids)),
        "stale": tuple(sorted(catalog_ids - live_ids)),
        "duplicate_live": tuple(
            sorted({value for value in live if live.count(value) > 1})
        ),
    }


def allows_ordinary_signal_activation(entry):
    return entry.activation_class == "signal-activatable"
