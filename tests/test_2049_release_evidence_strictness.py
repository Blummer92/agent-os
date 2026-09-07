from pathlib import Path


def test_release_evidence_does_not_coerce_canonical_scalars_or_collections():
    source = Path("scripts/agent-os-release-run.py").read_text(encoding="utf-8")
    assert 'repository=str(evidence.get("repository", ""))' not in source
    assert 'tuple(raw.get("source_identifiers", ()))' not in source
