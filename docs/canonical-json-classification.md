# Canonical JSON classification

Issue: #1733

## Rule

Agent OS does not have one repository-global canonical JSON contract. Similar
`json.dumps(...)` calls may be representation-equivalent while remaining
contract-distinct because their output feeds different identity domains,
persistence formats, validators, or external protocols.

Consolidation is permitted only when byte equivalence and dependency direction
are both proven safe.