"""Tests for ExecutionTracker functionality in quantTrader.

These tests validate that:
- Orders are properly submitted to broker and marked as submitted (not filled)
- Execution status is tracked properly through lifecycle
- Execution records are created with real data from broker
- Retry mechanism works for failed orders
"""

from unittest.mock import Mock, MagicMock
from quant_trader.execution_tracker import ExecutionTracker, ExecutionStatus


class FakeApiClient:
    """Fake API client for testing."""
    
    def __init__(self):
        self.signal_updates = []
        self.executions = []
    
    def update_signal_status(self, order_id, payload):
        self.signal_updates.append({
            "order_id": order_id,
            "payload": payload
        })
    
    def create_execution(self, execution):
        self.executions.append(execution)


class FakeBroker:
    """Fake broker for testing."""
    
    def __init__(self):
        self.placed_orders = []
        self.execution_responses = {}
        self.account_info = {
            "account_id": "TEST_ACCOUNT_1",
            "broker": "test_broker"
        }
    
    def place_order(self, signal):
        order_id = f"BROKER_{signal.get('order_id', '1')}"
        self.placed_orders.append(order_id)
        return order_id
    
    def get_execution_status(self):
        return self.execution_responses
    
    def get_account_info(self):
        return self.account_info


def test_submit_order_success():
    """Test successful order submission."""
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    
    signal = {
        "order_id": "ORDER_1",
        "symbol": "000001",
        "action": "buy",
        "size": 100,
        "price": 10.0
    }
    
    # Submit order
    success = tracker.submit_order(signal)
    
    # Verify success
    assert success is True
    assert len(broker.placed_orders) == 1
    assert len(api.signal_updates) == 1
    
    # Verify signal marked as submitted
    update = api.signal_updates[0]
    assert update["order_id"] == "ORDER_1"
    assert update["payload"]["status"] == "submitted"
    assert "qmt_order_id" in update["payload"]


def test_submit_order_failure():
    """Test order submission failure handling."""
    api = FakeApiClient()
    broker = FakeBroker()
    
    # Mock broker to fail
    broker.place_order = Mock(side_effect=Exception("Broker error"))
    
    tracker = ExecutionTracker(api_client=api, broker=broker)
    
    signal = {
        "order_id": "ORDER_2",
        "symbol": "000001",
        "action": "buy",
        "size": 100,
        "price": 10.0
    }
    
    # Submit order (should fail)
    success = tracker.submit_order(signal)
    
    # Verify failure handling
    assert success is False
    assert len(api.signal_updates) == 1
    
    # Verify marked as retry_pending
    update = api.signal_updates[0]
    assert update["order_id"] == "ORDER_2"
    assert update["payload"]["status"] == "retry_pending"
    assert update["payload"]["retry_count"] == 1
    assert "last_error" in update["payload"]


def test_poll_execution_status():
    """Test polling for execution status updates."""
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    
    # Submit an order first
    signal = {
        "order_id": "ORDER_3",
        "symbol": "000001",
        "action": "buy",
        "size": 100,
        "price": 10.0
    }
    tracker.submit_order(signal)
    
    # Set up broker to return execution status
    broker.execution_responses = {
        "BROKER_ORDER_3": {
            "status": "filled",
            "filled_size": 100,
            "avg_price": 10.05,
            "commission": 0.1
        }
    }
    
    # Poll for execution status
    tracker.poll_execution_status()
    
    # Verify execution was reported
    assert len(api.executions) == 1
    execution = api.executions[0]
    assert execution["order_id"] == "ORDER_3"
    assert execution["status"] == "filled"
    assert execution["filled_size"] == 100
    assert execution["filled_price"] == 10.05


def test_partial_fill_handling():
    """Test handling of partially filled orders."""
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    
    # Submit an order first
    signal = {
        "order_id": "ORDER_4",
        "symbol": "000001",
        "action": "buy",
        "size": 200,
        "price": 10.0
    }
    tracker.submit_order(signal)
    
    # Set up broker to return partial fill status
    broker.execution_responses = {
        "BROKER_ORDER_4": {
            "status": "partially_filled",
            "filled_size": 100,
            "avg_price": 10.05,
            "commission": 0.1
        }
    }
    
    # Poll for execution status
    tracker.poll_execution_status()
    
    # Verify partial fill was reported
    assert len(api.executions) == 1
    execution = api.executions[0]
    assert execution["order_id"] == "ORDER_4"
    assert execution["status"] in ["partial_filled", "partially_filled"]
    assert execution["filled_size"] == 100
    assert execution["filled_price"] == 10.05