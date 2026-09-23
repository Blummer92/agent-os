# Agent OS - Test Suite

Tests for Agent OS standards, governance, and implementations.

## Structure

```
tests/
├── conftest.py        # Shared pytest configuration and fixtures
├── unit/               # Unit tests for standards validation
├── integration/         # Integration tests for governance workflows
└── fixtures/            # Shared test data and mock objects
```

## Running Tests

Run these commands from the repository root. A virtual environment is recommended. Installing only `pytest` is insufficient: `validate-all.sh` checks the existing environment but does not install it. PyGithub comes from `requirements-dev.txt`, and the reusable registry must be installed editable so root tests can import it.

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -r 08_Tooling/workflow-scheduler/requirements.txt
python -m pip install -e "./08_Tooling/instructional-materials-coach[test]"
python -m pip install -e "./08_Tooling/notion-navigation-client[test]"
python -m pip install -e "./08_Tooling/reusable-capability-registry[test]"
./scripts/validate-all.sh
```

## Test Standards

Follows the standards in `01_Shared_Standards/python/` (see
`01_Shared_Standards/python/INDEX.md` for the full modular breakdown).

## Test Categories

**Unit tests** (`tests/unit/`): fast (< 100ms), isolated, test individual
standards/rules and documentation completeness.

**Integration tests** (`tests/integration/`): test workflows across
standards, governance procedures, and handoff processes; may involve
file I/O.

## Fixtures

See `conftest.py` for the full list (`repo_root`, `standards_dir`,
`python_standards_dir`, `templates_dir`, `governance_dir`, `temp_dir`,
`markdown_files`, `standard_files`, plus standard-document-specific
fixtures). Example usage:

```python
def test_all_standards_exist(standard_files):
    assert len(standard_files) > 0
    for standard in standard_files:
        assert standard.exists()
```

## CI/CD Integration

Tests run automatically via GitHub Actions on push to main, on pull
requests, and on manual trigger -- see
`01_Shared_Standards/python/ci-cd/github-actions.md`.

## Common Issues

Use the complete repository-root setup above before diagnosing collection errors. Do not skip or weaken validation to compensate for missing packages.

## Extending the Test Suite

1. Unit test: create `tests/unit/test_<module>.py`, a `Test<Module>`
   class, use fixtures from `conftest.py`.
2. Integration test: create `tests/integration/test_<workflow>.py`, mark
   with `@pytest.mark.integration`.
3. New fixture: add to `conftest.py` with `@pytest.fixture`, document it
   here.

## Coverage Targets

Overall >= 80%, standards validation >= 90%, governance tests >= 85%.

## Contributing

Use clear names (`test_<what>_<scenario>`), add a docstring explaining
the scenario, keep tests independent, and run `pytest` before committing.
