# Measuring Coverage

## Installation

```bash
pip install pytest-cov>=4.0.0
```

## Basic Measurement

```bash
# Measure and report in terminal
pytest --cov=src --cov-report=term-missing

# Fail if below threshold
pytest --cov=src --cov-fail-under=80

# Generate HTML report
pytest --cov=src --cov-report=html

# Multiple report formats
pytest --cov=src --cov-report=term-missing --cov-report=html --cov-report=xml
```

## Configuration

### In pytest.ini

```ini
[pytest]
addopts = --cov=src --cov-report=term-missing --cov-fail-under=80
```

### In setup.cfg

```ini
[coverage:run]
source = src
branch = True

[coverage:report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
```

## Branch Coverage

Test both branches of conditional logic:

```python
# Test both True and False paths
def test_condition_true():
    result = function(condition=True)
    assert result == expected_true

def test_condition_false():
    result = function(condition=False)
    assert result == expected_false
```

Enable branch coverage:

```bash
pytest --cov=src --cov=branch
```

Or in setup.cfg:

```ini
[coverage:run]
branch = True
```
