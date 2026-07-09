# Templates

Reusable prompts, project templates, report formats, and implementation guides.

## Quick Start

**New to Agent OS testing standards?** Start here:

- **[Quick-Start Testing Setup](./prompts/quick-start-testing-setup.md)** - 30-45 minute guide to set up pytest, fixtures, and CI/CD in a Python project

## Directories

### `/prompts`

Implementation guides and AI prompts for setting up testing and governance:

- **quick-start-testing-setup.md** - Step-by-step setup for new Python projects
- **implement-testing-strategy.md** - Comprehensive 8-week implementation strategy
- **update-agent-overlay.md** - Guidelines for updating agent role definitions
- **package-python-project.md** - Steps to package and distribute Python projects
- **bug-learning-review.md** - Process for reviewing bugs and extracting lessons
- **release-readiness-review.md** - Pre-release checklist
- **run-compliance-test.md** - Running compliance and security tests

### `/python-project-template`

Ready-to-use boilerplate for new Python projects:

- **pytest.ini** - pytest configuration with coverage settings
- **test_conftest.py** - Shared fixtures and test utilities
- **test_unit_template.py** - Example unit tests with AAA pattern
- **test_integration_template.py** - Example integration tests
- **folder-structure.md** - Recommended project directory layout
- **sample-readme.md** - Template README for projects
- **sample-pyproject.md** - pyproject.toml template
- **sample-env-example.md** - .env.example template
- **.github_workflows_tests.yml** - GitHub Actions CI/CD workflow

### `/reports`

Template formats for documentation and assessments:

- **testing-governance-implementation.md** - Report on testing governance alignment
- **qa-test-report-template.md** - Test execution and results reporting
- **final-report-template.md** - Project completion and lessons learned
- **bug-report-template.md** - Bug report structure
- **release-checklist-template.md** - Pre-release verification

## Usage

### For New Projects

1. Read: [Quick-Start Testing Setup](./prompts/quick-start-testing-setup.md)
2. Copy: Files from `python-project-template/` to your project
3. Reference: Standards in `01_Shared_Standards/python/`

### For Detailed Implementation

1. Start: [Implement Testing Strategy](./prompts/implement-testing-strategy.md)
2. Reference: Specific standards documents as needed
3. Report: Use templates in `/reports` to document progress

### For AI Agents

Use the prompt files to guide AI-assisted implementation:
- Paste the markdown content into an AI prompt
- Adapt the instructions for your specific context
- Use the templates as starting points, not rigid requirements
