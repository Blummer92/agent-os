from pathlib import Path


def test_issue_form_schema_does_not_stringify_malformed_collection_members():
    source = Path("scripts/agent_os_issue_labels/issue_metadata.py").read_text(encoding="utf-8")
    assert 'return tuple(str(item) for item in value)' not in source
    assert 'raw_id = str(field_id)' not in source
    assert 'label=str(label)' not in source
