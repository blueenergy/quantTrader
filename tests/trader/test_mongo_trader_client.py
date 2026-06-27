"""Unit tests for MongoTraderClient (mocked MongoDB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quant_trader.config import TraderConfig
from quant_trader.mongo_trader_client import MongoTraderClient


class FakeCursor:
    def __init__(self, docs: list) -> None:
        self._docs = list(docs)
        self._limit = len(self._docs)

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def __iter__(self):
        return iter(self._docs[: self._limit])


def _base_cfg() -> TraderConfig:
    return TraderConfig(
        backend_mode="db",
        mongo_uri="mongodb://127.0.0.1:27017",
        mongo_db="finance_test",
        user_id="user-1",
        securities_account_id="507f1f77bcf86cd799439011",
        api_base_url="",
        api_token="",
    )


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_get_pending_signals_sorts_sells_first(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db

    signals = MagicMock()
    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": MagicMock(),
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    doc_buy = {
        "_id": 1,
        "order_id": "b1",
        "action": "buy",
        "timestamp": 1.0,
        "execution_priority": 1000,
        "user_id": "user-1",
    }
    doc_sell = {
        "_id": 2,
        "order_id": "s1",
        "action": "sell",
        "timestamp": 2.0,
        "execution_priority": 1000,
        "user_id": "user-1",
    }
    signals.find.return_value = FakeCursor([doc_buy, doc_sell])

    client = MongoTraderClient(_base_cfg())
    out = client.get_pending_signals(limit=50, include_submitted=False)

    assert [s["order_id"] for s in out] == ["s1", "b1"]
    signals.find.assert_called_once()
    q = signals.find.call_args[0][0]
    assert q["user_id"] == "user-1"
    assert q["securities_account_id"] == "507f1f77bcf86cd799439011"
    assert q["is_executable"] is True
    assert q["mode"] == "live"


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_update_signal_status_not_found(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db
    signals = MagicMock()
    signals.find_one.return_value = None
    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": MagicMock(),
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())
    with pytest.raises(RuntimeError, match="Signal not found"):
        client.update_signal_status("missing", {"status": "submitted"})


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_are_plan_sells_terminal_blocks_on_in_flight_sell(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db
    signals = MagicMock()
    signals.find.return_value = FakeCursor(
        [
            {"order_id": "sell-1", "execution_phase": "sell", "status": "submitted"},
            {"order_id": "buy-1", "execution_phase": "buy", "status": "pending"},
        ]
    )
    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": MagicMock(),
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())

    assert client.are_plan_sells_terminal("plan-1") is False
    query = signals.find.call_args[0][0]
    assert query == {
        "user_id": "user-1",
        "plan_id": "plan-1",
        "mode": "live",
        "securities_account_id": "507f1f77bcf86cd799439011",
    }


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_are_plan_sells_terminal_allows_terminal_or_no_sells(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db
    signals = MagicMock()
    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": MagicMock(),
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())

    signals.find.return_value = FakeCursor(
        [
            {"order_id": "sell-1", "execution_phase": "sell", "status": "filled"},
            {"order_id": "sell-2", "execution_phase": "sell", "status": "cancelled"},
            {"order_id": "buy-1", "execution_phase": "buy", "status": "pending"},
        ]
    )
    assert client.are_plan_sells_terminal("plan-1") is True

    signals.find.return_value = FakeCursor([{"order_id": "buy-1", "execution_phase": "buy", "status": "pending"}])
    assert client.are_plan_sells_terminal("plan-1") is True


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_are_plan_sells_terminal_falls_back_to_action_for_legacy_sells(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db
    signals = MagicMock()
    signals.find.return_value = FakeCursor([{"order_id": "legacy-sell", "action": "SELL", "status": "partial_filled"}])
    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": MagicMock(),
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())

    assert client.are_plan_sells_terminal("plan-1") is False


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_create_execution_upserts_and_updates_signal(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db

    signals = MagicMock()
    executions = MagicMock()
    signals.find_one.return_value = {
        "order_id": "o1",
        "user_id": "user-1",
        "plan_id": "p1",
        "strategy_template_id": "st1",
    }
    executions.find_one.return_value = None

    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": executions,
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())
    client.create_execution(
        {
            "order_id": "o1",
            "symbol": "000001.SZ",
            "status": "filled",
            "filled_size": 100,
            "filled_price": 10.5,
            "timestamp": 12345.0,
        }
    )

    executions.insert_one.assert_called_once()
    inserted = executions.insert_one.call_args[0][0]
    assert inserted["user_id"] == "user-1"
    assert inserted["plan_id"] == "p1"
    signals.update_one.assert_called_once()
    sig_update = signals.update_one.call_args[0][1]["$set"]
    assert sig_update["status"] == "filled"
    assert sig_update["filled_qty"] == 100
    assert sig_update["avg_price"] == 10.5


@patch("quant_trader.mongo_trader_client.MongoClient")
def test_create_execution_updates_existing(mock_mongo):
    db = MagicMock()
    mock_mongo.return_value.__getitem__.return_value = db

    signals = MagicMock()
    executions = MagicMock()
    signals.find_one.return_value = {"order_id": "o1", "user_id": "user-1"}
    existing = {"_id": "exec1"}
    executions.find_one.return_value = existing

    db.__getitem__.side_effect = lambda name: {
        "trade_signals": signals,
        "trade_executions": executions,
        "worker_status": MagicMock(),
        "trader_positions": MagicMock(),
        "trader_accounts": MagicMock(),
        "position_snapshots": MagicMock(),
        "securities_accounts": MagicMock(),
    }[name]

    client = MongoTraderClient(_base_cfg())
    client.create_execution({"order_id": "o1", "status": "partial_filled", "filled_size": 50})

    executions.update_one.assert_called_once()
    executions.insert_one.assert_not_called()


def test_create_trader_client_api_mode():
    from quant_trader.api_client import TraderApiClient
    from quant_trader.client_factory import create_trader_client

    cfg = TraderConfig(
        backend_mode="api",
        api_base_url="http://localhost:8000/api",
        api_token="token",
        mongo_uri=None,
        user_id=None,
    )
    client = create_trader_client(cfg)
    assert isinstance(client, TraderApiClient)
