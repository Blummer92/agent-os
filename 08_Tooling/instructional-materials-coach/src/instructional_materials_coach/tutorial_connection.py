"""Prerequisite tutorial connection for worksheets (#3215).

Units assume tutorial days whose tool moves transfer into the worksheet
work. Those tutorials are typed data here, not prose convention: each
registered tutorial names the exact tool moves it teaches, and lesson
content declares its prerequisites by tutorial id
(``LessonContent.prerequisite_tutorials``). Unknown tutorial ids fail
closed at generation time instead of silently dropping the connection.

``generation_context.compose_generation_context`` projects the resolved
moves as context tokens and supplies a standard "tutorial connection"
section default (mirroring the #1568 warm-up/exit-ticket defaults): a
student-facing paragraph that names the transfer moves and gives students
who missed the tutorial a catch-up pointer. Governed curriculum values
still win and are never duplicated.

This module performs no I/O and grants no authority.
"""
from __future__ import annotations

import dataclasses
from typing import Mapping


class TutorialConnectionError(ValueError):
    """A prerequisite tutorial id cannot be resolved against the registry."""


@dataclasses.dataclass(frozen=True)
class TutorialRecord:
    """One registered tutorial day: title plus the tool moves it teaches."""

    tutorial_id: str
    title: str
    moves: tuple[str, ...]


#: The typed tutorial registry. Tutorial 0 is the Adobe Express
#: favorite-food reference setup the Motion Spot unit assumes (#3215):
#: students can make a static branded image and can locate Text,
#: recommended fonts, alignment/spacing, and Export.
TUTORIALS: Mapping[str, TutorialRecord] = {
    "tutorial-0": TutorialRecord(
        tutorial_id="tutorial-0",
        title="Tutorial 0 - Adobe Express favorite-food reference setup",
        moves=("Text", "Recommended fonts", "Alignment and spacing", "Export"),
    ),
}


def resolve_tutorial(tutorial_id: str) -> TutorialRecord:
    """Resolve one tutorial id against the typed registry.

    Fail closed on unknown ids: a mistyped prerequisite must never silently
    drop the tutorial-day connection.
    """
    if not isinstance(tutorial_id, str) or not tutorial_id.strip():
        raise TutorialConnectionError("tutorial id must be non-empty text")
    record = TUTORIALS.get(tutorial_id.strip())
    if record is None:
        known = ", ".join(sorted(TUTORIALS))
        raise TutorialConnectionError(
            f"unknown prerequisite tutorial {tutorial_id!r}; known tutorials: {known}"
        )
    return record


def tutorial_transfer_paragraph(tutorial_id: str) -> str:
    """Student-facing paragraph naming the transfer moves plus a catch-up pointer.

    Names the exact tool moves the tutorial taught and tells students who
    missed the tutorial where the moves come from, so no worksheet assumes
    tool fluency it never names.
    """
    record = resolve_tutorial(tutorial_id)
    moves = _join_moves(record.moves)
    return (
        f"Tutorial connection: use the {moves} moves from {record.title} "
        "in today's build. Missed that tutorial? Ask for the catch-up before "
        "you start - you need these moves to build."
    )


def _join_moves(moves: tuple[str, ...]) -> str:
    lowered = [move.lower() for move in moves]
    if len(lowered) == 1:
        return lowered[0]
    return ", ".join(lowered[:-1]) + ", and " + lowered[-1]
