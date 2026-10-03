"""Single governed material-type vocabulary (#3254).

Three vocabularies collapse here:
- MaterialRequirement ``SUPPORTED_ARTIFACT_TYPES`` (e.g. "teacher-guide",
  "slide-deck", "worksheet")
- IMC ``_TEACHER_REFERENCE_MATERIAL_TYPE`` ("teacher-reference")
- Visual Asset Library "Approved use" live values
  (worksheet/slide/poster/student-facing/teacher-facing)

The governed stable IDs are the contract-facing values. "student-facing" /
"teacher-facing" are audience values in the VAL, not material types; the
mapping separates audience from material type instead of conflating them.

``teacher-guide`` is the governed ID for the teacher-reference split
(matching MaterialRequirement); IMC's "teacher-reference" is a deprecated
alias that maps to it.

Unknown values map to None: the caller must route to manual review, never
invent a mapping and never drop the value silently.
"""

from __future__ import annotations

MATERIAL_TYPE_VOCABULARY: dict[str, dict[str, tuple[str, ...]]] = {
    "worksheet": {
        "material_requirement": (),
        "imc": (),
        "val": ("worksheet",),
    },
    "slide-deck": {
        "material_requirement": ("slide-deck",),
        "imc": (),
        "val": ("slide",),
    },
    "poster": {
        "material_requirement": (),
        "imc": (),
        "val": ("poster",),
    },
    "teacher-guide": {
        "material_requirement": ("teacher-guide",),
        "imc": ("teacher-reference",),
        "val": ("teacher-facing",),
    },
    "student-facing": {
        "material_requirement": (),
        "imc": (),
        "val": ("student-facing",),
    },
}

# Reverse index: (source, raw_value) -> governed stable ID.
_MATERIAL_TYPE_REVERSE: dict[tuple[str, str], str] = {}
for _governed, _sources in MATERIAL_TYPE_VOCABULARY.items():
    for _source, _values in _sources.items():
        for _value in _values:
            _MATERIAL_TYPE_REVERSE[(_source, _value)] = _governed


def map_material_type(raw_value: object, source: str) -> str | None:
    """Map a source vocabulary value to the governed material-type stable ID.

    Returns None when the value is missing or unmappable: the caller must
    route to manual review, never invent a mapping and never drop the value
    silently. ``source`` is one of "material_requirement", "imc", "val".
    """
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().lower()
    if not normalized:
        return None
    return _MATERIAL_TYPE_REVERSE.get((source, normalized))


def governed_material_types() -> tuple[str, ...]:
    """Return the governed stable IDs in deterministic order."""
    return tuple(sorted(MATERIAL_TYPE_VOCABULARY))
