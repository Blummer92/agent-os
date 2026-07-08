# Code Quality Checks

## Tools Required

```bash
pip install flake8 black mypy isort
```

## Linting with flake8

Detects style violations and bugs:

```bash
# Check all Python files
flake8 src tests

# Show statistics
flake8 --statistics src

# Only show certain violations
flake8 --select=E501,W503 src
```

In CI/CD:

```yaml
- name: Lint with flake8
  run: |
    flake8 src tests --count --select=E,W,F --show-source
```

## Code Formatting with black

Auto-format code consistently:

```bash
# Check formatting
black --check src tests

# Auto-format
black src tests
```

In CI/CD:

```yaml
- name: Format with black
  run: black --check src tests
```

## Import Sorting with isort

Organize imports:

```bash
# Check import order
isort --check-only src tests

# Auto-sort
isort src tests
```

## Type Checking with mypy

Check type hints:

```bash
# Check types
mypy src

# Ignore missing imports
mypy src --ignore-missing-imports
```

In CI/CD:

```yaml
- name: Type check with mypy
  run: mypy src
```

## Combined Quality Check

Full CI/CD job:

```yaml
- name: Code quality
  run: |
    flake8 src tests
    black --check src tests
    mypy src
    isort --check-only src tests
```

## Configuration Files

### .flake8

```ini
[flake8]
max-line-length = 88
extend-ignore = E203, W503
exclude = .git,__pycache__,venv
```

### pyproject.toml (for black)

```toml
[tool.black]
line-length = 88
target-version = ['py39']

[tool.isort]
profile = "black"
line_length = 88
```

### mypy.ini

```ini
[mypy]
python_version = 3.9
warn_return_any = True
strict = False
ignore_missing_imports = True
```
