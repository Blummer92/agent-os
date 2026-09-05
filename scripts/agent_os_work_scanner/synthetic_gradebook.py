from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any


SYNTHETIC_GRADEBOOK_FIXTURE_VERSION = "1.0"


class FixtureMode(str, Enum):
    EDITABLE = "editable"
    READ_ONLY = "read-only"


class FixtureFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"


class FixtureError(RuntimeError):
    pass


class ReadOnlyFixtureError(FixtureError):
    pass


class StaleFixtureError(FixtureError):
    pass


class RecoverableFixtureError(FixtureError):
    pass


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: str
    ids: tuple[str, ...]


class SyntheticGradebookFixture:
    """Deterministic, local-only gradebook state for LMS/SIS contract tests."""

    def __init__(self) -> None:
        self._baseline = _baseline_state()
        self.reset()

    @property
    def version(self) -> str:
        return SYNTHETIC_GRADEBOOK_FIXTURE_VERSION

    @property
    def digest(self) -> str:
        payload = json.dumps(self._baseline, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def reset(self) -> None:
        self.state = copy.deepcopy(self._baseline)
        self.mode = FixtureMode.EDITABLE
        self.freshness = FixtureFreshness.CURRENT
        self.confirmation_modal = False
        self.recoverable_error = False
        self.selector_drift = False
        self.pending_write: dict[str, Any] | None = None

    def set_mode(self, mode: FixtureMode) -> None:
        self.mode = mode

    def set_stale(self, stale: bool = True) -> None:
        self.freshness = FixtureFreshness.STALE if stale else FixtureFreshness.CURRENT

    def set_selector_drift(self, drifted: bool = True) -> None:
        self.selector_drift = drifted

    def set_recoverable_error(self, enabled: bool = True) -> None:
        self.recoverable_error = enabled

    def stable_selector(self, kind: str, identity: str) -> str:
        if self.selector_drift:
            return f'[data-testid="missing-{kind}-{identity}"]'
        return f'[data-testid="{kind}-{identity}"]'

    def fragile_selector(self, kind: str, identity: str) -> str:
        return f"#{kind}_{identity}_a8f91_generated"

    def match_student(self, query: str) -> MatchResult:
        return _match(self.state["students"], query)

    def match_assignment(self, query: str) -> MatchResult:
        return _match(self.state["assignments"], query)

    def list_students(self, *, page: int = 1, page_size: int = 2, query: str | None = None) -> tuple[dict[str, Any], ...]:
        rows = list(self.state["students"])
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in row["name"].casefold()]
        start = max(page - 1, 0) * page_size
        return tuple(copy.deepcopy(rows[start : start + page_size]))

    def visible_grade(self, student_id: str, assignment_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.state["grades"][_grade_key(student_id, assignment_id)])

    def begin_grade_write(self, student_id: str, assignment_id: str, score: Decimal | None, comment: str = "") -> None:
        if self.mode == FixtureMode.READ_ONLY:
            raise ReadOnlyFixtureError("synthetic gradebook is read-only")
        if self.freshness == FixtureFreshness.STALE:
            raise StaleFixtureError("synthetic visible state is stale")
        if self.recoverable_error:
            self.recoverable_error = False
            raise RecoverableFixtureError("synthetic recoverable write error")
        key = _grade_key(student_id, assignment_id)
        if key not in self.state["grades"]:
            raise KeyError(key)
        self.pending_write = {
            "key": key,
            "score": None if score is None else str(Decimal(score)),
            "comment": comment.strip(),
        }
        self.confirmation_modal = True

    def confirm_grade_write(self) -> dict[str, Any]:
        if not self.confirmation_modal or self.pending_write is None:
            raise FixtureError("no synthetic grade write awaiting confirmation")
        pending = self.pending_write
        grade = self.state["grades"][pending["key"]]
        grade["score"] = pending["score"]
        grade["comment"] = pending["comment"]
        self.pending_write = None
        self.confirmation_modal = False
        return copy.deepcopy(grade)


def _match(rows: list[dict[str, Any]], query: str) -> MatchResult:
    needle = query.strip().casefold()
    matches = tuple(row["id"] for row in rows if needle and needle in row["name"].casefold())
    if not matches:
        return MatchResult("not-found", ())
    if len(matches) > 1:
        return MatchResult("ambiguous", matches)
    return MatchResult("resolved", matches)


def _grade_key(student_id: str, assignment_id: str) -> str:
    return f"{student_id}:{assignment_id}"


def _baseline_state() -> dict[str, Any]:
    students = [
        {"id": "student-01", "name": "Learner Alpha"},
        {"id": "student-02", "name": "Learner Alpine"},
        {"id": "student-03", "name": "Learner Beta"},
    ]
    assignments = [
        {"id": "assignment-01", "name": "Composition Study"},
        {"id": "assignment-02", "name": "Composition Study Revised"},
        {"id": "assignment-03", "name": "Lighting Exercise"},
    ]
    rubric = [
        {"id": "criterion-craft", "description": "Synthetic craft criterion", "points": "5"},
        {"id": "criterion-analysis", "description": "Synthetic analysis criterion", "points": "5"},
    ]
    grades = {
        _grade_key("student-01", "assignment-01"): {"score": "8", "comment": "Synthetic feedback A", "rubric": rubric},
        _grade_key("student-02", "assignment-01"): {"score": None, "comment": "", "rubric": rubric},
        _grade_key("student-03", "assignment-01"): {"score": "6", "comment": "Synthetic feedback B", "rubric": rubric},
        _grade_key("student-01", "assignment-02"): {"score": "9", "comment": "Synthetic feedback C", "rubric": rubric},
        _grade_key("student-02", "assignment-02"): {"score": "7", "comment": "Synthetic feedback D", "rubric": rubric},
        _grade_key("student-03", "assignment-02"): {"score": None, "comment": "", "rubric": rubric},
        _grade_key("student-01", "assignment-03"): {"score": "10", "comment": "Synthetic feedback E", "rubric": rubric},
        _grade_key("student-02", "assignment-03"): {"score": "5", "comment": "Synthetic feedback F", "rubric": rubric},
        _grade_key("student-03", "assignment-03"): {"score": "8", "comment": "Synthetic feedback G", "rubric": rubric},
    }
    return {"students": students, "assignments": assignments, "grades": grades}
