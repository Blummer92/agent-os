# Async Testing

## Setup

pytest-asyncio required:

```
pytest-asyncio>=0.21.0
```

## Basic Async Test

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    """Mark async tests with @pytest.mark.asyncio."""
    result = await async_function()
    assert result == expected
```

## Async Fixtures

```python
@pytest.fixture
async def async_client():
    """Async fixture for async client."""
    client = AsyncClient()
    await client.connect()
    yield client
    await client.disconnect()

@pytest.mark.asyncio
async def test_with_async_fixture(async_client):
    result = await async_client.get('/endpoint')
    assert result.status_code == 200
```

## pytest.ini Configuration

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
markers =
    asyncio: marks tests as async
```

## Testing Concurrent Operations

```python
@pytest.mark.asyncio
async def test_concurrent():
    """Test multiple async operations."""
    import asyncio
    results = await asyncio.gather(
        async_op1(),
        async_op2(),
        async_op3()
    )
    assert len(results) == 3
```

## Mocking Async Functions

```python
@pytest.mark.asyncio
async def test_mock_async(mocker):
    """Mock async function."""
    mock_func = mocker.AsyncMock(return_value='result')
    result = await mock_func()
    assert result == 'result'
    mock_func.assert_called_once()
```
