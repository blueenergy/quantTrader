"""Tests for TraderLoop with Execution Tracking functionality.

These tests validate that:
- TraderLoop properly initializes execution tracker
- Signals are submitted through execution tracker (not immediately filled)
- Execution lifecycle is properly managed
- Position sync still works with new execution tracking
"""

from unittest.mock import Mock, patch, MagicMock
from quant_trader.trader_loop import TraderLoop
from quant_trader.config import TraderConfig
from quant_trader.execution_tracker import ExecutionTracker


class MockApiClient:
    """Mock API client for testing."""
    
    def __init__(self):
        self.signal_updates = []
        self.executions = []
        self.position_updates = []
        self.account_syncs = []
    
    def get_pending_signals(self, limit=50, include_submitted=False):
        # Return a test signal
        return [{
            "order_id": "ORDER_1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "account_id": "ACC_X"
        }]
    
    def update_signal_status(self, order_id, payload):
        self.signal_updates.append({
            "order_id": order_id,
            "payload": payload
        })
    
    def create_execution(self, execution):
        self.executions.append(execution)
    
    def update_position(self, position_data):
        self.position_updates.append(position_data)
        return {"status": "success"}
    
    def sync_account(self, account_data):
        self.account_syncs.append(account_data)
        return {"status": "success"}


class MockBroker:
    """Mock broker for testing."""
    
    def __init__(self):
        self.placed_orders = []
        self.positions = {}
        self.account_info = {
            "account_id": "ACC_X",
            "broker": "test_broker"
        }
    
    def place_order(self, signal):
        order_id = f"BROKER_{signal.get('order_id', '1')}"
        self.placed_orders.append(order_id)
        return order_id
    
    def get_positions(self):
        return self.positions
    
    def get_account_info(self):
        return self.account_info
    
    def get_execution_status(self):
        # Return filled status for testing
        if self.placed_orders:
            return {
                self.placed_orders[-1]: {
                    "status": "filled",
                    "filled_size": 100,
                    "avg_price": 10.05,
                    "commission": 0.1
                }
            }
        return {}
    
    def close(self):
        pass


def test_trader_loop_initialization():
    """Test TraderLoop initialization with execution tracking."""
    cfg = TraderConfig(
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    
    api = MockApiClient()
    broker = MockBroker()
    
    # Initialize with execution tracking enabled
    loop = TraderLoop(
        cfg=cfg,
        api=api,
        broker=broker,
        enable_execution_tracking=True,
        enable_position_sync=True
    )
    
    # Verify execution tracker is initialized
    assert loop.execution_tracker is not None
    assert isinstance(loop.execution_tracker, ExecutionTracker)
    
    # Verify position manager is initialized
    assert loop.position_manager is not None


def test_trader_loop_signal_handling():
    """Test signal handling with execution tracking."""
    cfg = TraderConfig(
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    
    api = MockApiClient()
    broker = MockBroker()
    
    loop = TraderLoop(
        cfg=cfg,
        api=api,
        broker=broker,
        enable_execution_tracking=True,
        enable_position_sync=False  # Disable for this test
    )
    
    # Get a test signal
    signals = api.get_pending_signals()
    
    # Handle the signal
    loop._handle_signal(signals[0])
    
    # Verify signal was processed through execution tracker
    assert len(broker.placed_orders) == 1
    assert len(api.signal_updates) == 1
    
    # Verify signal marked as submitted, not filled
    update = api.signal_updates[0]
    assert update["order_id"] == "ORDER_1"
    assert update["payload"]["status"] == "submitted"  # Should be submitted, not filled
    assert "qmt_order_id" in update["payload"]
    
    # Verify no execution was created yet (should wait for actual fill)
    assert len(api.executions) == 0


def test_trader_loop_execution_polling():
    """Test execution polling functionality."""
    cfg = TraderConfig(
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    
    api = MockApiClient()
    broker = MockBroker()
    
    loop = TraderLoop(
        cfg=cfg,
        api=api,
        broker=broker,
        enable_execution_tracking=True,
        enable_position_sync=False
    )
    
    # First, submit a signal
    signal = {
        "order_id": "ORDER_2",
        "symbol": "000001",
        "action": "buy",
        "size": 200,
        "price": 15.0
    }
    
    loop._handle_signal(signal)
    
    # Now poll for execution status
    loop.execution_tracker.poll_execution_status()
    
    # Verify execution was created after polling
    assert len(api.executions) == 1
    execution = api.executions[0]
    assert execution["order_id"] == "ORDER_2"
    assert execution["status"] == "filled"
    assert execution["filled_size"] == 100  # From mock broker
    assert execution["filled_price"] == 10.05


def test_trader_loop_without_execution_tracking():
    """Test trader loop without execution tracking (fallback behavior)."""
    cfg = TraderConfig(
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    
    api = MockApiClient()
    broker = MockBroker()
    
    # Initialize with execution tracking disabled
    loop = TraderLoop(
        cfg=cfg,
        api=api,
        broker=broker,
        enable_execution_tracking=False,
        enable_position_sync=False
    )
    
    # Get a test signal
    signals = api.get_pending_signals()
    
    # Handle the signal (should use fallback behavior)
    loop._handle_signal(signals[0])
    
    # Verify fallback behavior created execution immediately
    assert len(api.executions) == 1
    execution = api.executions[0]
    assert execution["order_id"] == "ORDER_1"
    assert execution["status"] == "filled"  # Should be filled immediately