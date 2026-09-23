# Type Checking with mypy

## Installation

```bash
pip install mypy
```

## Type Checking

```bash
mypy src                            # Check types
mypy src --ignore-missing-imports   # Allow missing stubs
mypy src --strict                   # Strict mode
```

## Configuration

Create `mypy.ini`:

```ini
[mypy]
python_version = 3.9
warn_return_any = True
ignore_missing_imports = True
```

Or in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.9"
warn_return_any = true
ignore_missing_imports = true
```

## In CI/CD

```yaml
- name: Type check
  run: mypy src
```

## Type Hints

```python
# Annotate function parameters and return type
def greet(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

# Annotate variables
count: int = 0
users: list[str] = []
config: dict[str, Any] = {}
```

## Common Issues

```python
# Missing return type
def calculate():  # ✗ Add return type
    pass

# Fixed
def calculate() -> int:  # ✓ Type specified
    return 42

# Missing parameter types
def add(a, b):  # ✗ Missing types
    return a + b

# Fixed
def add(a: int, b: int) -> int:  # ✓ All typed
    return a + b
```

## Integration with Linting

See [linting-formatting.md](linting-formatting.md) for flake8, black, and isort.

Run all checks:

```bash
flake8 src tests && \
black --check src tests && \
mypy src && \
isort --check-only src tests
```
