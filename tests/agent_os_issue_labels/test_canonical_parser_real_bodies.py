"""Regression tests: canonical metadata parser must handle real issue bodies (#3092).

Investigation (2026-10-08) proved `managed_labels_for_create` raised ValueError on
all 17 sampled real issue bodies, while the existing suite passed on synthetic
inputs only. Failure classes observed in production:

- bare `key:value` metadata lead blocks (e.g. #3407) were rejected outright:
  "canonical tiered metadata is required before connected issue creation"
  (the parser only read `## `/`### ` sections);
- tiered `## ` bodies containing ordinary prose (e.g. #3092) failed with
  "unmapped canonical metadata cannot authorize managed labels" (section prose
  was ingested as label values).

Two parse functions now share the recognized shapes:

- `parse_issue_form_body`: full-fidelity parse (backward compatible — free-text
  fields still round-trip for draft validation and duplicate-review evidence)
  plus bare `key:value` lead-block recognition.
- `parse_label_metadata`: strict metadata-shaped values only; prose is ignored.
  Used by `managed_labels_for_create` and the connected-creation facade.

Fixtures below are sanitized representatives of those real body shapes (metadata
lines preserved, prose trimmed), each annotated with its source issue.
"""

import pytest

from scripts.agent_os_issue_labels.connected_issue_creation import (
    managed_labels_for_create,
)
from scripts.agent_os_issue_labels.issue_metadata import (
    load_issue_form_fields,
    metadata_contract,
    parse_issue_form_body,
    parse_label_metadata,
)

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

EXPECTED = (
    "agent-os",
    "owner:chatgpt-orchestrator",
    "status:needs-decision",
    "type:bug",
)

# Sanitized from #3407: bare key:value metadata lines precede the first heading.
BARE_KV_BODY = """tier:1-standard-implementation
owner:chatgpt-orchestrator
status:needs-decision
type:bug
Source of truth: GitHub
External-write boundary: no-external-write

## Reproduction

The draft PR description claims shared editing makes splitting artificial.
The paragraph in the shared standard was edited by both changes.
"""

# Sanitized from #3092: canonical ## sections whose content mixes metadata lines
# with ordinary explanatory prose.
PROSE_SECTIONS_BODY = """## Issue tier

tier:1-standard-implementation

## Objective and value

Prevent connected issue creation from reaching terminal success before labels converge.

## Primary owner

owner:chatgpt-orchestrator

Repository implementation executor only if a real repository-owned host-consumed seam is proven.

## Readiness candidate

status:needs-decision

The repository contract is already explicit on current main, but the connected host can still bypass it.

## Work type

type:bug

## Source of truth

GitHub

## External write boundary

no-external-write
"""

# Sanitized from #3397: free-form incident report with no canonical metadata.
FREEFORM_BODY = """## Bug

Renovate onboarding is blocked by an invalid packageRules configuration.

## Reproduction

Open the repository settings and observe the validation error on the config file.
"""

# Canonical value shape with a genuinely unknown owner identity.
UNMAPPED_VALUE_BODY = """## Issue tier

tier:1-standard-implementation

## Primary owner

owner:nobody-has-this-identity

## Readiness candidate

status:needs-decision

## Work type

type:bug

## Source of truth

GitHub

## External write boundary

no-external-write
"""


def _fields():
    return load_issue_form_fields(FORM)


def _kw():
    return {"issue_form_path": FORM, "label_map_path": MAP}


def test_bare_kv_lead_block_reaches_tiered_contract():
    metadata = parse_issue_form_body(BARE_KV_BODY, _fields())
    assert metadata_contract(metadata) == "tiered"


def test_bare_kv_lead_block_extracts_exact_metadata():
    metadata = parse_issue_form_body(BARE_KV_BODY, _fields())
    assert metadata["tier"] == ["tier:1-standard-implementation"]
    assert metadata["owner"] == ["owner:chatgpt-orchestrator"]
    assert metadata["status"] == ["status:needs-decision"]
    assert metadata["type"] == ["type:bug"]
    assert metadata["source-of-truth"] == ["GitHub"]
    assert metadata["external-write"] == ["no-external-write"]
    # The ## Reproduction prose must not leak into any field.
    for values in metadata.values():
        for value in values:
            assert "artificial" not in value


def test_bare_kv_body_plans_expected_labels():
    labels = managed_labels_for_create(BARE_KV_BODY, **_kw())
    assert set(labels) == set(EXPECTED)


def test_strict_parse_accepts_bare_kv_lead():
    metadata = parse_label_metadata(BARE_KV_BODY, _fields())
    assert metadata_contract(metadata) == "tiered"
    assert metadata["owner"] == ["owner:chatgpt-orchestrator"]


def test_strict_parse_ignores_prose_in_sections():
    metadata = parse_label_metadata(PROSE_SECTIONS_BODY, _fields())
    assert metadata_contract(metadata) == "tiered"
    assert metadata["owner"] == ["owner:chatgpt-orchestrator"]
    assert metadata["status"] == ["status:needs-decision"]
    for values in metadata.values():
        for value in values:
            assert "host-consumed seam" not in value
            assert "already explicit" not in value


def test_prose_sections_body_plans_expected_labels():
    labels = managed_labels_for_create(PROSE_SECTIONS_BODY, **_kw())
    assert set(labels) == set(EXPECTED)


def test_full_parse_preserves_free_text_for_draft_roundtrip():
    # Backward compatibility: full-fidelity parsing still returns free-text
    # field content (draft validation and duplicate-review evidence depend
    # on it); only the strict label-metadata parse drops prose.
    metadata = parse_issue_form_body(PROSE_SECTIONS_BODY, _fields())
    assert any("host-consumed seam" in v for v in metadata["owner"])
    assert any("already explicit" in v for v in metadata["status"])


def test_freeform_body_still_fails_closed():
    metadata = parse_label_metadata(FREEFORM_BODY, _fields())
    assert metadata_contract(metadata) != "tiered"
    with pytest.raises(ValueError, match="canonical tiered metadata is required"):
        managed_labels_for_create(FREEFORM_BODY, **_kw())


def test_genuinely_unmapped_value_still_fails_closed():
    with pytest.raises(ValueError, match="unmapped canonical metadata"):
        managed_labels_for_create(UNMAPPED_VALUE_BODY, **_kw())


def test_cross_field_key_prefix_is_dropped_not_misattributed():
    body = "## Primary owner\n\nstatus:blocked\n"
    metadata = parse_label_metadata(body, {"owner": "Primary owner"})
    assert metadata.get("owner", []) == []


def test_unknown_bare_key_is_ignored():
    body = "frobnicate:yes\ntier:1-standard-implementation\n\n## Reproduction\n\ntext\n"
    metadata = parse_issue_form_body(body, _fields())
    assert "frobnicate" not in metadata
    assert metadata["tier"] == ["tier:1-standard-implementation"]


def test_h4_content_is_not_lead_block_metadata():
    # Content under deeper non-metadata headings is neither a section nor
    # lead-block metadata.
    metadata = parse_issue_form_body(
        "#### Work type\n\ntype:bug\n", {"type": "Work type"}
    )
    assert metadata == {}


def test_multiword_legitimate_values_are_accepted():
    body = (
        "## Issue tier\n\ntier:1-standard-implementation\n\n"
        "## Primary owner\n\nowner:chatgpt-orchestrator\n\n"
        "## Readiness candidate\n\nstatus:needs-decision\n\n"
        "## Work type\n\ntype:bug\n\n"
        "## Source of truth\n\nNotion handoff\n\n"
        "## External write boundary\n\nno-external-write\n"
    )
    metadata = parse_issue_form_body(body, _fields())
    assert metadata["source-of-truth"] == ["Notion handoff"]
    assert set(managed_labels_for_create(body, **_kw())) == set(EXPECTED)


def test_canonical_h2_body_still_plans_expected_labels():
    body = (
        "## Issue tier\n\ntier:1-standard-implementation\n\n"
        "## Primary owner\n\nowner:chatgpt-orchestrator\n\n"
        "## Readiness candidate\n\nstatus:needs-decision\n\n"
        "## Work type\n\ntype:bug\n\n"
        "## Source of truth\n\nGitHub\n\n"
        "## External write boundary\n\nno-external-write\n"
    )
    assert set(managed_labels_for_create(body, **_kw())) == set(EXPECTED)
