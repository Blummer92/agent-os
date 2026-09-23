# Linting and Code Formatting

## Tools

```bash
pip install flake8 black isort
```

## Linting with flake8

Detects style violations and bugs:

```bash
flake8 src tests                    # Check files
flake8 --statistics src             # Show summary
flake8 --select=E501,W503 src      # Check specific rules
```

## Formatting with black

Auto-format code:

```bash
black --check src tests             # Check formatting
black src tests                     # Auto-format
```

## Import Sorting with isort

Organize imports:

```bash
isort --check-only src tests       # Check order
isort src tests                     # Auto-sort
```

## In CI/CD

```yaml
- name: Lint with flake8
  run: flake8 src tests

- name: Format with black
  run: black --check src tests

- name: Sort imports
  run: isort --check-only src tests
```

## Configuration Files

### .flake8

```ini
[flake8]
max-line-length = 88
extend-ignore = E203, W503
exclude = .git,__pycache__,venv
```

### pyproject.toml

```toml
[tool.black]
line-length = 88
target-version = ['py39']

[tool.isort]
profile = "black"
line_length = 88
```
