# Error and Exception Testing

## Test Error Propagation

```python
import pytest

@pytest.mark.integration
def test_error_propagates_through_layers(self, test_db):
    """Test error propagates from data layer to API."""
    # Invalid data that triggers database error
    with pytest.raises(IntegrityError):
        user = User(id=1, name='First')
        test_db.add(user)
        test_db.commit()
        
        # Try to add duplicate
        user2 = User(id=1, name='Duplicate')
        test_db.add(user2)
        test_db.commit()
```

## Test Error Handling at Each Layer

```python
def test_database_error_handling(self, test_db):
    """Test database errors are handled correctly."""
    try:
        # Cause database error
        test_db.query(User).delete()
        test_db.commit()
        test_db.execute('SELECT * FROM nonexistent_table')
    except OperationalError as e:
        assert 'no such table' in str(e).lower()

def test_validation_error_handling(self):
    """Test validation errors are caught."""
    with pytest.raises(ValidationError) as exc_info:
        validate_email('not-an-email')
    
    assert 'invalid email' in str(exc_info.value).lower()
```

## Test API Error Responses

```python
@pytest.mark.integration
def test_api_returns_error_on_validation_failure(client):
    """Test API returns proper error response."""
    response = client.post('/users', json={
        'name': '',  # Invalid: empty name
        'email': 'test@example.com'
    })
    
    assert response.status_code == 400
    data = response.get_json()
    assert data['error'] == 'Validation error'
    assert 'name' in data['details']
```

## Test Graceful Degradation

```python
def test_handle_missing_external_service(client, mocker):
    """Test graceful failure when external service is down."""
    # Mock service to raise error
    mocker.patch('email_service.send', side_effect=Exception('Service down'))
    
    response = client.post('/users', json={
        'name': 'John',
        'email': 'john@example.com'
    })
    
    # Should still succeed, but without email
    assert response.status_code == 201
    data = response.get_json()
    assert data['id'] is not None
    assert data.get('email_sent') is False
```

## Test Timeout Handling

```python
def test_timeout_on_slow_operation(client, mocker):
    """Test timeout on slow external calls."""
    # Mock slow operation
    def slow_operation():
        import time
        time.sleep(10)
        return 'done'
    
    mocker.patch('external.slow_operation', side_effect=slow_operation)
    
    with pytest.raises(TimeoutError):
        response = client.get('/slow-endpoint', timeout=1)
```

## Test Recovery from Errors

```python
def test_retry_after_transient_failure(mocker):
    """Test retry logic on transient failures."""
    call_count = 0
    
    def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError('Temporary failure')
        return 'success'
    
    mocker.patch('api.call', side_effect=failing_function)
    
    result = retry_with_backoff(failing_function, max_attempts=3)
    assert result == 'success'
    assert call_count == 3
```
