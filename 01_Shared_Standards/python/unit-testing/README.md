# Unit Testing Standards

## Quick Links

- **[patterns.md](patterns.md)** - AAA pattern and test structure
- **[naming-conventions.md](naming-conventions.md)** - Test naming
- **[assertions.md](assertions.md)** - Assertion best practices
- **[parametrization.md](parametrization.md)** - Parameterized tests

## What Are Unit Tests?

Unit tests verify individual functions/classes in isolation:

- **Fast:** < 100ms per test
- **Isolated:** No external dependencies
- **Deterministic:** Same result every run
- **Independent:** Don't depend on other tests

## File Organization

```
tests/unit/
├── test_models.py
├── test_validators.py
├── test_cli.py
└── test_utils.py
```

## Naming Convention

- File: `test_*.py`
- Class: `Test*`
- Method: `test_*`

Example: `test_user_validator.py`

## Running Unit Tests

```bash
pytest tests/unit                    # Run all unit tests
pytest tests/unit -v                # Verbose output
pytest tests/unit --cov=src         # With coverage
pytest tests/unit -k test_validate  # Run specific tests
```
