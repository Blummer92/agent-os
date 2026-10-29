"""M19 regression tests: criterion identity must not alias (mutation escape).

Mutation M19 changes the criterion-identity digest truncation in
``scripts/agent_os_issue_acceptance/criterion_preservation.py`` from
``digest[:12]`` to ``digest[:0]``::

    def _criterion_identity(index: int, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"criterion-{index}-{digest[:12]}"   # mutated: digest[:0]

Under that mutation every criterion at a given index gets the identity
``criterion-<index>-`` — an empty digest suffix — so two *different*
criterion texts at the *same* position silently alias to one identity.

Why the pre-existing tests did not detect M19:

* Identities in a single parsed body were only asserted distinct across
  *different indexes* (``len({c.identity ...}) == 3`` for indexes 1-3),
  and the index prefix alone keeps those distinct even with an empty
  digest.
* ``AcceptanceCriterion.__post_init__`` and packet verification compare
  an identity against the *same* (mutated) production function, so they
  stay self-consistent under the mutation.
* ``verify_criterion_packet`` checks ``text`` before ``identity``, so a
  reworded criterion is caught as reworded for its text, never proving
  that its identity changed.
* No test asserted the identity's shape (non-empty, 12-char hex digest
  suffix), its exact digest value, or that rewording one criterion at
  the same position changes its identity.

These tests therefore exercise the *real* production identity path —
``_criterion_identity`` and the public parsers / packet builder /
satisfaction projection that call it — at a *fixed* position, where the
digest is the only thing that can distinguish two texts. They do not
reimplement the identity function in the test.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from scripts.agent_os_issue_acceptance.criterion_preservation import (
    AcceptanceCriterion,
    _criterion_identity,
    build_criterion_packet,
    parse_acceptance_criteria,
    parse_criteria_section,
)
from scripts.agent_os_issue_acceptance.criterion_satisfaction import (
    project_criterion_satisfaction,
)

# The documented contract (module docstring + _criterion_identity):
# identity is "criterion-<1-based index>-<first 12 hex chars of the
# sha256 of the exact criterion text>".
_IDENTITY_RE = re.compile(r"^criterion-(\d+)-([0-9a-f]{12})$")

TEXT_A = "First criterion stays exact."
TEXT_B = "First criterion stays exact!"  # one-character rewording of TEXT_A
TEXT_C = "A completely different first criterion."


def _body(*texts: str) -> str:
    lines = "\n".join(f"- [ ] {text}" for text in texts)
    return f"## Acceptance criteria\n\n{lines}\n"


def _identity_of_single(text: str) -> str:
    criteria = parse_acceptance_criteria(_body(text))
    assert len(criteria) == 1
    assert criteria[0].index == 1
    return criteria[0].identity


# --- 1. Identical wording at the same position: same identity ------------


def test_identical_wording_same_position_produces_same_identity() -> None:
    assert _identity_of_single(TEXT_A) == _identity_of_single(TEXT_A)
    assert _criterion_identity(1, TEXT_A) == _criterion_identity(1, TEXT_A)
    # Deterministic across repeated parses of the same body.
    first = parse_acceptance_criteria(_body(TEXT_A, TEXT_C))
    second = parse_acceptance_criteria(_body(TEXT_A, TEXT_C))
    assert [c.identity for c in first] == [c.identity for c in second]


def test_identical_wording_same_position_same_identity_via_packet() -> None:
    packet_a = build_criterion_packet(_body(TEXT_A))
    packet_b = build_criterion_packet(_body(TEXT_A))
    assert packet_a["criteria"] == packet_b["criteria"]
    assert packet_a["criteria"][0]["identity"] == _identity_of_single(TEXT_A)


# --- 2. Reworded wording at the same position: different identity --------


@pytest.mark.parametrize(
    ("original", "reworded"),
    [
        (TEXT_A, TEXT_B),  # punctuation only
        (TEXT_A, TEXT_C),  # completely different wording
        (TEXT_A, "first criterion stays exact."),  # case only
        (TEXT_A, "First criterion stays  exact."),  # whitespace only
        (TEXT_A, "First criterion stays exact"),  # trailing period dropped
    ],
)
def test_reworded_criterion_same_position_produces_different_identity(
    original: str, reworded: str
) -> None:
    assert _criterion_identity(1, original) != _criterion_identity(1, reworded)
    assert _identity_of_single(original) != _identity_of_single(reworded)


def test_reworded_second_criterion_changes_only_its_own_identity() -> None:
    original = parse_acceptance_criteria(_body(TEXT_A, "Second criterion."))
    reworded = parse_acceptance_criteria(
        _body(TEXT_A, "Second criterion, restated.")
    )
    assert original[0].identity == reworded[0].identity
    assert original[1].index == reworded[1].index == 2
    assert original[1].identity != reworded[1].identity


def test_packet_identity_changes_when_criterion_is_reworded() -> None:
    packet_a = build_criterion_packet(_body(TEXT_A))
    packet_b = build_criterion_packet(_body(TEXT_B))
    assert packet_a["criteria"][0]["index"] == packet_b["criteria"][0]["index"]
    assert packet_a["criteria"][0]["identity"] != packet_b["criteria"][0]["identity"]


def test_satisfaction_projection_identity_changes_when_criterion_reworded() -> None:
    proj_a = project_criterion_satisfaction(_body(TEXT_A))
    proj_b = project_criterion_satisfaction(_body(TEXT_B))
    assert len(proj_a.criteria) == len(proj_b.criteria) == 1
    assert proj_a.criteria[0].identity != proj_b.criteria[0].identity
    # Preservation and satisfaction assign the same identity to the same line.
    assert proj_a.criteria[0].identity == _identity_of_single(TEXT_A)


# --- 3. Different identities cannot silently alias -------------------------


def test_identity_suffix_is_nonempty_12_char_lowercase_hex() -> None:
    for text in (TEXT_A, TEXT_B, TEXT_C, "x", "Only criterion."):
        for index in (1, 2, 7):
            identity = _criterion_identity(index, text)
            match = _IDENTITY_RE.match(identity)
            assert match is not None, identity
            assert int(match.group(1)) == index
            suffix = match.group(2)
            assert len(suffix) == 12
            assert suffix != ""
            # The identity must not end in the aliased empty-digest form.
            assert not identity.endswith("-")


def test_identity_suffix_is_exact_sha256_prefix_of_exact_text() -> None:
    # Pin the contract's digest value, not just its shape: the suffix is
    # the first 12 hex chars of sha256(exact text). Under M19 the suffix
    # is "" and this fails; under any other truncation it also fails.
    for text in (TEXT_A, TEXT_B, TEXT_C):
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        assert _criterion_identity(3, text) == f"criterion-3-{expected}"
        assert _identity_of_single(text) == f"criterion-1-{expected}"


def test_distinct_texts_at_same_position_never_share_identity() -> None:
    texts = [
        TEXT_A,
        TEXT_B,
        TEXT_C,
        "First criterion stays exact..",
        "First criterion stays exact. ",
        "Second criterion is preserved verbatim.",
        "Third criterion carries its identity.",
    ]
    # Trailing-space text is stripped by the parser, so use the production
    # function for the raw set and the parser for the parsable set; both
    # must be injective at a fixed position.
    identities = [_criterion_identity(1, text) for text in texts]
    assert len(set(identities)) == len(texts)

    parsed_identities = [
        _identity_of_single(text) for text in (TEXT_A, TEXT_B, TEXT_C)
    ]
    assert len(set(parsed_identities)) == 3


def test_section_entries_at_same_position_do_not_alias_when_reworded() -> None:
    entries_a = parse_criteria_section(_body(TEXT_A))
    entries_b = parse_criteria_section(_body(TEXT_C))
    assert entries_a is not None and entries_b is not None
    assert entries_a[0].index == entries_b[0].index == 1
    assert entries_a[0].identity != entries_b[0].identity


def test_acceptance_criterion_rejects_empty_digest_identity() -> None:
    # The M19 aliased identity for TEXT_A at index 1 is "criterion-1-".
    # It must never validate against the real text.
    with pytest.raises(ValueError, match="identity does not match"):
        AcceptanceCriterion(index=1, text=TEXT_A, identity="criterion-1-")


def test_acceptance_criterion_rejects_identity_of_a_different_text() -> None:
    aliased = _criterion_identity(1, TEXT_A)
    with pytest.raises(ValueError, match="identity does not match"):
        AcceptanceCriterion(index=1, text=TEXT_C, identity=aliased)
    # And the production identity for its own text validates.
    criterion = AcceptanceCriterion(index=1, text=TEXT_C, identity=_criterion_identity(1, TEXT_C))
    assert criterion.identity != aliased


def test_same_text_at_different_positions_has_different_identity() -> None:
    # Position is part of the identity contract; this also guards that
    # the assertions above are not passing merely because of the index.
    assert _criterion_identity(1, TEXT_A) != _criterion_identity(2, TEXT_A)
    criteria = parse_acceptance_criteria(_body(TEXT_A, TEXT_A))
    assert criteria[0].identity != criteria[1].identity
