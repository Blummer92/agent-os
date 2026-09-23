# Workflow Testing

## Test Complete Workflows

Integration tests verify multiple components working together.

## Pattern: Setup → Execute → Verify

```python
import pytest

@pytest.mark.integration
class TestUserCreationWorkflow:
    """Test complete user creation workflow."""
    
    def test_create_user_with_validation(self, test_db):
        """User creation triggers all validators."""
        # SETUP - Create necessary data
        email = 'newuser@example.com'
        password = 'SecurePass123!'
        
        # EXECUTE - Run complete workflow
        user = create_user_with_validation(
            email=email,
            password=password
        )
        
        # VERIFY - All side effects occurred
        assert user.email == email
        assert user.is_active is True
        assert user.created_at is not None
        
        # Verify it's in database
        found = test_db.session.query(User).filter_by(email=email).first()
        assert found.id == user.id
```

## Test State Transitions

```python
def test_order_workflow(self, test_db):
    """Test complete order processing workflow."""
    # Create order (PENDING)
    order = create_order(user=user, items=items)
    assert order.status == 'PENDING'
    
    # Process payment (PROCESSING)
    order.process_payment()
    assert order.status == 'PROCESSING'
    
    # Fulfill order (COMPLETED)
    order.fulfill()
    assert order.status == 'COMPLETED'
    assert order.fulfilled_at is not None
```

## Test Data Relationships

```python
def test_user_has_multiple_orders(self, test_db):
    """Test user can have multiple related orders."""
    user = create_test_user()
    
    # Create multiple orders
    order1 = create_order(user=user, total=100)
    order2 = create_order(user=user, total=200)
    
    # Verify relationships
    assert len(user.orders) == 2
    assert sum(o.total for o in user.orders) == 300
```

## Test Event Sequences

```python
def test_notification_workflow(self, test_db):
    """Test notifications are sent in correct order."""
    events = []
    
    def capture_event(event):
        events.append(event)
    
    # Subscribe to events
    subscribe_to_events(capture_event)
    
    # Execute workflow
    order = create_order(...)
    
    # Verify sequence
    assert events[0].type == 'ORDER_CREATED'
    assert events[1].type == 'PAYMENT_PROCESSED'
    assert events[2].type == 'FULFILLMENT_STARTED'
```
