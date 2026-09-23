# Coverage Requirements

## Version

- Coverage tool: 6.0.0+
- pytest-cov: 4.0.0+

## Minimum Targets

| Category | Target | Rationale |
|----------|--------|-----------|
| Overall project | 80% | Typical production standard |
| Critical modules | 90% | Validators, safety-critical code |
| Data models | 85% | Business logic verification |
| Utilities | 75% | Helper functions, less risky |
| Configuration | 0% | Auto-generated, excluded |
| Generated code | 0% | Excluded from coverage |

## Coverage Scope

### Always Include

- Business logic (src/)
- Data models
- Validators
- CLI handlers
- API endpoints
- Report builders

### Exclude

- Type stubs (.pyi files)
- Generated code
- Configuration files
- Third-party imports

## Acceptable Gaps

```python
# pragma: no cover
def rarely_used_fallback():
    """This code is rarely executed in normal flow."""
    return default_value
```

Use `# pragma: no cover` only for:
- Intentional defensive code
- Error conditions that can't be tested
- Platform-specific code
