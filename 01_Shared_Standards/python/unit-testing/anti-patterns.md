# Anti-Patterns to Avoid

```python
# ✗ Don't: Test implementation instead of behavior
def test_loop_iterates_three_times():
    ...  # Only cares about loop mechanics, not the actual result

# ✗ Don't: Share state between tests
@pytest.fixture(scope="session")
def shared_database():
    ...  # Tests will interfere with each other

# ✗ Don't: Mock too much
def test_function(mocker):
    mocker.patch("builtins.print")
    ...  # Can't tell if the code actually works

# ✗ Don't: Test too many things at once
def test_user_workflow():
    ...  # Validate, save, fetch, delete -- split into separate tests

# ✗ Don't: Make tests dependent on each other
def test_1_setup():
    ...  # Sets up data
def test_2_uses_data():
    ...  # Depends on test_1 having already run

# ✗ Don't: Use sleep() for timing
def test_async_operation():
    sleep(1)
    assert result  # Slow and unreliable -- poll or await instead

# ✗ Don't: Test random behavior without seeding
def test_shuffle():
    random.shuffle(items)  # Non-deterministic

# ✗ Don't: Hardcode the same test data across multiple files
# tests/test_a.py
test_email = "john@example.com"
# tests/test_b.py
test_email = "john@example.com"  # Duplicated -- use a shared fixture

# ✗ Don't: Name a test after a bug ticket with no context
def test_broken_bug():
    ...  # What bug? Which version? Name it after the behavior instead
```
