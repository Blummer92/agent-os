from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "05_Roadmap/capability-roadmap-registry.md"
INHERITANCE = ROOT / "04_Registry/agent-inheritance-registry.md"
ALIASES = ROOT / "04_Registry/legacy-agent-alias-registry.md"


def _table_rows(text: str, headers: tuple[str, ...]) -> list[list[str]]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if cells != headers:
            continue
        rows: list[list[str]] = []
        for row_line in lines[index + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            rows.append([cell.strip() for cell in row_line.strip().strip("|").split("|")])
        return rows
    return []


def _canonical_agents() -> set[str]:
    rows = _table_rows(
        INHERITANCE.read_text(encoding="utf-8"),
        ("Agent", "Inherits", "Overlay"),
    )
    return {row[0] for row in rows if len(row) == 3 and all(row)}


def _active_aliases() -> set[str]:
    rows = _table_rows(
        ALIASES.read_text(encoding="utf-8").split("## Ambiguous Legacy Values", 1)[0],
        ("Legacy Name / Property", "Canonical Agent", "Current Overlay", "Status", "Notes"),
    )
    return {row[0] for row in rows if len(row) == 5 and "active alias" in row[3].lower()}


def test_live_capability_roadmap_uses_only_canonical_primary_owners():
    agents = _canonical_agents()
    aliases = _active_aliases()
    rows = _table_rows(
        ROADMAP.read_text(encoding="utf-8"),
        (
            "ID",
            "Capability",
            "Purpose",
            "Primary Owner",
            "Canonical Roadmap or Parent",
            "Stage",
            "Current Evidence",
            "Primary Blocker or Next Gate",
        ),
    )

    assert rows, "Capability Registry table is missing or empty"
    for row in rows:
        assert len(row) == 8
        capability_id, owner_value = row[0], row[3]
        owners = [owner.strip() for owner in owner_value.split("/")]
        assert owners and all(owners)
        for owner in owners:
            assert owner not in aliases, (
                f"{capability_id} writes retired alias {owner!r} as a live primary owner"
            )
            assert owner in agents, (
                f"{capability_id} has unknown live primary owner {owner!r}"
            )


def test_live_capability_roadmap_documents_alias_writeback_rule():
    text = ROADMAP.read_text(encoding="utf-8")
    assert "## Owner Identity Rule" in text
    assert "legacy-agent-alias-registry.md" in text
    assert "must be resolved" in text
    assert "written back" in text
