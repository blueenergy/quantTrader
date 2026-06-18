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

    def cancel_order(self, broker_order_id, **kwargs):
        return True


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
    assert execution["commission"] == 0.1
    assert execution["estimated_fee"] is False


def test_poll_execution_status_estimates_fee_when_broker_fee_missing():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)

    tracker.submit_order({
        "order_id": "ORDER_FEE",
        "symbol": "000001",
        "action": "sell",
        "size": 100,
        "price": 10.0,
    })
    broker.execution_responses = {
        "BROKER_ORDER_FEE": {
            "status": "filled",
            "filled_size": 100,
            "avg_price": 10.0,
        }
    }

    tracker.poll_execution_status()

    execution = api.executions[0]
    assert execution["estimated_fee"] is True
    assert execution["commission"] == 5.0
    assert execution["stamp_tax"] == 0.5
    assert execution["total_fee"] == 5.5


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


def test_attach_existing_order_preserves_live_signal_metadata():
    """Test restart recovery keeps broker mapping and live signal metadata."""
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)

    signal = {
        "order_id": "ORDER_RECOVER",
        "broker_order_id": 987654,
        "symbol": "000001.SZ",
        "action": "buy",
        "size": 300,
        "price": 12.3,
        "status": "partial_filled",
        "filled_qty": 100,
        "avg_price": 12.1,
        "submitted_at": 12345.0,
        "securities_account_id": "SEC123",
        "account_id": "ACC123",
        "broker": "miniQMT",
        "mode": "live",
        "strategy_id": "portfolio_s1",
    }

    assert tracker.attach_existing_order(signal) is True

    execution = tracker._pending_executions["ORDER_RECOVER"]
    assert execution.status == ExecutionStatus.PARTIAL_FILLED
    assert execution.broker_order_id == "987654"
    assert execution.filled_size == 100
    assert execution.filled_price == 12.1
    assert execution.securities_account_id == "SEC123"
    assert execution.account_id == "ACC123"
    assert execution.broker == "miniQMT"
    assert execution.mode == "live"
    assert execution.strategy == "portfolio_s1"
    assert execution.created_at == 12345.0
    assert execution.submitted_at == 12345.0
    assert tracker._broker_to_order_map["987654"] == "ORDER_RECOVER"


def test_attach_existing_cancel_requested_order_preserves_tracking():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)

    signal = {
        "order_id": "ORDER_CANCEL_REQ",
        "broker_order_id": 1234,
        "symbol": "000001.SZ",
        "action": "sell",
        "size": 300,
        "status": "cancel_requested",
        "filled_qty": 100,
        "reference_price": 10.0,
        "effective_limit_price": 9.95,
    }

    assert tracker.attach_existing_order(signal) is True

    execution = tracker._pending_executions["ORDER_CANCEL_REQ"]
    assert execution.status == ExecutionStatus.CANCEL_REQUESTED
    assert execution.filled_size == 100
    assert tracker._broker_to_order_map["1234"] == "ORDER_CANCEL_REQ"


def test_sell_order_uses_protected_limit_price():
    api = FakeApiClient()
    broker = FakeBroker()
    captured = {}

    def place_order(signal):
        captured.update(signal)
        return "BROKER_SELL"

    broker.place_order = place_order
    tracker = ExecutionTracker(api_client=api, broker=broker)

    signal = {
        "order_id": "ORDER_SELL",
        "symbol": "000001",
        "action": "sell",
        "size": 100,
        "reference_price": 10.0,
        "max_slippage_bps": 50,
    }

    assert tracker.submit_order(signal) is True
    assert captured["order_type"] == "limit"
    assert captured["price"] == 9.95
    assert captured["effective_limit_price"] == 9.95
    assert api.signal_updates[0]["payload"]["effective_limit_price"] == 9.95


def test_protected_prices_are_rounded_to_tick():
    api = FakeApiClient()
    broker = FakeBroker()
    captured = {}

    def place_order(signal):
        captured[signal["order_id"]] = dict(signal)
        return f"BROKER_{signal['order_id']}"

    broker.place_order = place_order
    tracker = ExecutionTracker(api_client=api, broker=broker)

    assert tracker.submit_order(
        {
            "order_id": "ORDER_SELL_TICK",
            "symbol": "000001",
            "action": "sell",
            "size": 100,
            "reference_price": 10.005,
            "max_slippage_bps": 50,
        }
    )
    assert tracker.submit_order(
        {
            "order_id": "ORDER_BUY_TICK",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price_ceiling": 10.055,
        }
    )

    assert captured["ORDER_SELL_TICK"]["effective_limit_price"] == 9.95
    assert captured["ORDER_BUY_TICK"]["effective_limit_price"] == 10.06


def test_sell_order_without_reference_price_is_not_submitted():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)

    signal = {
        "order_id": "ORDER_NO_REF",
        "symbol": "000001",
        "action": "sell",
        "size": 100,
    }

    assert tracker.submit_order(signal) is False
    assert broker.placed_orders == []
    assert api.signal_updates[0]["payload"]["status"] == "retry_pending"
    assert api.signal_updates[0]["payload"]["last_error"] == "missing_reference_price"


def test_expired_sell_order_requests_cancel():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    tracker.submit_order(
        {
            "order_id": "ORDER_EXPIRE",
            "symbol": "000001",
            "action": "sell",
            "size": 100,
            "reference_price": 10.0,
            "valid_until": 1,
        }
    )
    broker.execution_responses = {
        "BROKER_ORDER_EXPIRE": {
            "status": "submitted",
            "filled_size": 0,
            "avg_price": None,
        }
    }

    tracker.poll_execution_status()

    assert api.signal_updates[-1]["payload"]["status"] == "cancel_requested"
    assert api.signal_updates[-1]["payload"]["last_error"] == "sell_order_expired_cancel_requested"
    assert api.signal_updates[-1]["payload"]["remaining_size"] == 100
    suggestion = api.signal_updates[-1]["payload"]["chase_suggestion"]
    assert suggestion["auto_resubmit"] is False
    assert suggestion["mode"] == "manual_review"
    assert suggestion["reason"] == "sell_order_expired"
    assert suggestion["remaining_size"] == 100
    assert suggestion["suggested_limit_price"] == 9.87


def test_expired_buy_order_requests_cancel():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    tracker.buy_order_timeout_seconds = 0.0
    tracker.submit_order(
        {
            "order_id": "ORDER_BUY_EXPIRE",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price_ceiling": 10.5,
            "reference_price": 10.0,
            "max_slippage_bps": 100,
        }
    )
    broker.execution_responses = {
        "BROKER_ORDER_BUY_EXPIRE": {
            "status": "submitted",
            "filled_size": 0,
            "avg_price": None,
            "last_price": 10.2,
        }
    }

    tracker.poll_execution_status()

    assert api.signal_updates[-1]["payload"]["status"] == "cancel_requested"
    assert api.signal_updates[-1]["payload"]["last_error"] == "buy_order_expired_cancel_requested"
    suggestion = api.signal_updates[-1]["payload"]["chase_suggestion"]
    assert suggestion["reason"] == "buy_order_expired"
    assert suggestion["action"] == "buy"
    assert suggestion["auto_resubmit"] is False


def test_partial_cancelled_records_remaining_size_and_chase_suggestion():
    api = FakeApiClient()
    broker = FakeBroker()
    tracker = ExecutionTracker(api_client=api, broker=broker)
    tracker.submit_order(
        {
            "order_id": "ORDER_PART_CANCEL",
            "symbol": "000001",
            "action": "sell",
            "size": 300,
            "reference_price": 10.0,
        }
    )
    broker.execution_responses = {
        "BROKER_ORDER_PART_CANCEL": {
            "status": "partial_cancelled",
            "filled_size": 100,
            "avg_price": 9.95,
        }
    }

    tracker.poll_execution_status()

    execution = api.executions[-1]
    assert execution["status"] == "partial_cancelled"
    assert execution["remaining_size"] == 200
    assert execution["chase_suggestion"]["remaining_size"] == 200
    assert execution["chase_suggestion"]["auto_resubmit"] is False
