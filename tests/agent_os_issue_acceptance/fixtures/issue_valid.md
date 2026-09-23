# Build issue

```yaml
agent_os_issue_acceptance:
  owner_agent: qa-test-agent
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - scripts/agent_os_issue_acceptance/
  forbidden_paths:
    - 00_Governance/
  required_tests:
    - tests/agent_os_issue_acceptance/
  required_docs:
    - scripts/agent_os_issue_acceptance/README.md
  banned_patterns:
    - import requests
  manual_review: []
```
