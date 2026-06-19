"""Tests for TraderLoop with Execution Tracking functionality.

These tests validate that:
- TraderLoop properly initializes execution tracker
- Signals are submitted through execution tracker (not immediately filled)
- Execution lifecycle is properly managed
- Position sync still works with new execution tracking
"""

from datetime import datetime, timezone
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
        self.heartbeats = []
        self.sell_barrier_satisfied = True
        self.sell_barrier_error = None
    
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

    def get_submitted_signals(self, limit=100):
        return []

    def are_plan_sells_terminal(self, plan_id):
        if self.sell_barrier_error:
            raise self.sell_barrier_error
        return self.sell_barrier_satisfied
    
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

    def record_heartbeat(self, payload):
        self.heartbeats.append(payload)
        return {"success": True}


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

    def query_positions(self):
        return self.positions

    def query_account(self):
        return {
            "available_cash": 100000,
            "cash": 100000,
            "total_asset": 100000,
            "market_value": 0,
        }
    
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
        backend_mode="api",
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
        backend_mode="api",
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
        backend_mode="api",
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
        backend_mode="api",
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


def test_trader_loop_records_heartbeat_with_rate_limit(monkeypatch):
    """Test heartbeat payload and 30-second rate limiting."""
    cfg = TraderConfig(
        backend_mode="api",
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
        enable_position_sync=True
    )

    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: 1000.0)
    loop._record_heartbeat()
    loop._record_heartbeat()

    assert len(api.heartbeats) == 1
    heartbeat = api.heartbeats[0]
    assert heartbeat["status"] == "running"
    assert heartbeat["broker"] == "MockBroker"
    assert heartbeat["api_base_url"] == "http://test:8000"
    assert heartbeat["pending_execution_count"] == 0
    assert heartbeat["last_signal_poll_at"] == 1000.0
    assert heartbeat["account_id"] == "ACC_X"

    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: 1031.0)
    loop._record_heartbeat()
    assert len(api.heartbeats) == 2


def test_trader_loop_orders_sells_before_buys():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=False, enable_position_sync=False)

    sell_signals, buy_signals = loop._split_ordered_signals([
        {"order_id": "BUY_1", "action": "buy", "execution_priority": 1, "timestamp": 1},
        {"order_id": "SELL_1", "action": "sell", "execution_priority": 5, "timestamp": 2},
        {"order_id": "SELL_0", "action": "sell", "execution_priority": 1, "timestamp": 3},
    ])

    assert [sig["order_id"] for sig in sell_signals] == ["SELL_0", "SELL_1"]
    assert [sig["order_id"] for sig in buy_signals] == ["BUY_1"]


def test_trader_loop_cash_gates_buy_orders():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {"order_id": "BUY_BIG", "symbol": "000001", "action": "buy", "size": 1000, "price": 20.0},
        account={"available_cash": 1000},
    )

    assert broker.placed_orders == []
    assert api.signal_updates[0]["payload"]["status"] == "retry_pending"
    assert "waiting_for_cash" in api.signal_updates[0]["payload"]["last_error"]


def test_trader_loop_sell_barrier_off_allows_buy():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="off",
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = False
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_OFF",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_OFF"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_sell_barrier_hard_waits_for_in_flight_sell():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="hard",
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = False
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_WAIT",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == []
    assert api.signal_updates == []


def test_trader_loop_sell_barrier_hard_allows_when_sells_terminal():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="hard",
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = True
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_CLEAR",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_CLEAR"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_sell_barrier_soft_shadow_allows_buy():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="soft",
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = False
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_SOFT",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_SOFT"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_sell_barrier_query_error_allows_buy():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="hard",
    )
    api = MockApiClient()
    api.sell_barrier_error = RuntimeError("mongo down")
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_DBDOWN",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_DBDOWN"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_sell_barrier_undecidable_allows_buy():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="hard",
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = None
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {
            "order_id": "BUY_UNKNOWN",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_UNKNOWN"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_sell_barrier_timeout_allows_buy(monkeypatch):
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        sell_barrier_mode="hard",
        sell_barrier_timeout_seconds=30,
    )
    api = MockApiClient()
    api.sell_barrier_satisfied = False
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)
    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: 100.0)

    loop._handle_signal(
        {
            "order_id": "BUY_TIMEOUT",
            "plan_id": "plan-1",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "created_at": 10.0,
            "phase_barrier": {"type": "plan_sells_terminal", "plan_id": "plan-1"},
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_TIMEOUT"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_waits_for_activate_after(monkeypatch):
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        use_activate_after=True,
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)
    now = datetime(2026, 6, 19, 1, 0, tzinfo=timezone.utc).timestamp()
    activate_after = datetime(2026, 6, 19, 1, 30, tzinfo=timezone.utc).isoformat()
    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: now)

    loop._handle_signal(
        {
            "order_id": "BUY_LATER",
            "symbol": "000001",
            "action": "buy",
            "size": 100,
            "price": 10.0,
            "activate_after": activate_after,
        },
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == []
    assert api.signal_updates == []


def test_trader_loop_waits_outside_configured_session(monkeypatch):
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        trading_sessions="CN_A",
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)
    saturday_cn_open = datetime(2026, 6, 20, 2, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: saturday_cn_open)

    loop._handle_signal(
        {"order_id": "BUY_WEEKEND", "symbol": "000001", "action": "buy", "size": 100, "price": 10.0},
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == []
    assert api.signal_updates == []


def test_trader_loop_allows_cn_a_session_from_0925(monkeypatch):
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0,
        trading_sessions="CN_A",
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)
    cn_0925 = datetime(2026, 6, 19, 1, 25, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("quant_trader.trader_loop.time.time", lambda: cn_0925)

    loop._handle_signal(
        {"order_id": "BUY_OPEN", "symbol": "000001", "action": "buy", "size": 100, "price": 10.0},
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == ["BROKER_BUY_OPEN"]
    assert api.signal_updates[0]["payload"]["status"] == "submitted"


def test_trader_loop_resume_tracks_cancel_requested_order():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    api = MockApiClient()
    api.get_submitted_signals = lambda limit=100: [
        {
            "order_id": "ORDER_CANCEL_REQ",
            "broker_order_id": "BROKER_CANCEL_REQ",
            "status": "cancel_requested",
            "symbol": "000001",
            "action": "sell",
            "size": 100,
        }
    ]
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    assert loop.execution_tracker.attach_existing_order(api.get_submitted_signals()[0]) is True
    assert loop.execution_tracker.is_tracking("ORDER_CANCEL_REQ") is True


def test_trader_loop_retries_buy_without_price_for_cash_check():
    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://test:8000",
        api_token="test_token",
        securities_account_id="SEC123",
        poll_interval=1.0
    )
    api = MockApiClient()
    broker = MockBroker()
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_execution_tracking=True, enable_position_sync=False)

    loop._handle_signal(
        {"order_id": "BUY_NO_PRICE", "symbol": "000001", "action": "buy", "size": 1000},
        account={"available_cash": 100000},
    )

    assert broker.placed_orders == []
    assert api.signal_updates[0]["payload"]["status"] == "retry_pending"
    assert api.signal_updates[0]["payload"]["last_error"] == "missing_buy_price_for_cash_check"
