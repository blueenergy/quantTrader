"""Unit tests for MiniQMTBroker without requiring a real miniQMT runtime."""

from __future__ import annotations

import sys
import types

from quant_trader.broker_miniQMT import MiniQMTBroker


class _FakeStockAccount:
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id


class _FakeXtTrader:
    instances = []

    def __init__(self, xt_path: str, session_id: int) -> None:
        self.xt_path = xt_path
        self.session_id = session_id
        self.started = False
        self.connected = False
        self.subscribed_account = None
        self.order_calls = []
        self.cancel_calls = []
        self.orders = []
        _FakeXtTrader.instances.append(self)

    def start(self):
        self.started = True

    def connect(self):
        self.connected = True
        return 0

    def subscribe(self, account):
        self.subscribed_account = account
        return 0

    def order_stock(self, *args):
        self.order_calls.append(args)
        return 123456

    def cancel_order_stock(self, *args):
        self.cancel_calls.append(args)
        return 0

    def query_stock_orders(self, account):
        return self.orders

    def unsubscribe(self, account):
        return 0

    def stop(self):
        return 0


def _install_fake_xtquant(monkeypatch):
    _FakeXtTrader.instances = []

    xtquant = types.ModuleType("xtquant")
    xttrader = types.ModuleType("xtquant.xttrader")
    xttype = types.ModuleType("xtquant.xttype")
    xtconstant = types.ModuleType("xtquant.xtconstant")

    xttrader.XtQuantTrader = _FakeXtTrader
    xttype.StockAccount = _FakeStockAccount
    xtconstant.STOCK_BUY = 23
    xtconstant.STOCK_SELL = 24
    xtconstant.MARKET_PEER_PRICE_FIRST = 41
    xtconstant.FIX_PRICE = 42
    xtconstant.ORDER_JUNK = 51
    xtconstant.ORDER_CANCELED = 55
    xtconstant.ORDER_SUCCEEDED = 53
    xtconstant.ORDER_PART_SUCCEEDED = 52
    xtconstant.ORDER_PARTSUCC_CANCEL = 54
    xtconstant.ORDER_REPORTED = 50
    xtconstant.ORDER_WAIT_REPORTING = 56

    xtquant.xttrader = xttrader
    xtquant.xttype = xttype
    xtquant.xtconstant = xtconstant

    monkeypatch.setitem(sys.modules, "xtquant", xtquant)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader)
    monkeypatch.setitem(sys.modules, "xtquant.xttype", xttype)
    monkeypatch.setitem(sys.modules, "xtquant.xtconstant", xtconstant)
    return xtconstant


def _broker(monkeypatch):
    xtconstant = _install_fake_xtquant(monkeypatch)
    broker = MiniQMTBroker(xt_path="/fake/qmt", account_id="ACC123")
    trader = _FakeXtTrader.instances[-1]
    return broker, trader, xtconstant


def test_miniqmt_broker_initializes_fake_xtquant(monkeypatch):
    broker, trader, _ = _broker(monkeypatch)

    assert trader.started is True
    assert trader.connected is True
    assert trader.subscribed_account.account_id == "ACC123"

    broker.close()


def test_miniqmt_place_order_uses_effective_limit_price(monkeypatch):
    broker, trader, xtconstant = _broker(monkeypatch)

    broker_order_id = broker.place_order(
        {
            "order_id": "ORDER_SELL",
            "symbol": "000001",
            "action": "sell",
            "size": 100,
            "price": 10.0,
            "effective_limit_price": 9.95,
            "order_type": "limit",
        }
    )

    assert broker_order_id == "123456"
    account, symbol, side, volume, price_type, price = trader.order_calls[-1]
    assert account.account_id == "ACC123"
    assert symbol == "000001.SZ"
    assert side == xtconstant.STOCK_SELL
    assert volume == 100
    assert price_type == xtconstant.FIX_PRICE
    assert price == 9.95


def test_miniqmt_place_order_respects_market_order_type(monkeypatch):
    broker, trader, xtconstant = _broker(monkeypatch)

    broker.place_order(
        {
            "order_id": "ORDER_BUY",
            "symbol": "600000",
            "action": "buy",
            "size": 200,
            "price": 10.0,
            "order_type": "market",
        }
    )

    _, symbol, side, volume, price_type, price = trader.order_calls[-1]
    assert symbol == "600000.SH"
    assert side == xtconstant.STOCK_BUY
    assert volume == 200
    assert price_type == xtconstant.MARKET_PEER_PRICE_FIRST
    assert price == 0.0


def test_miniqmt_cancel_order_calls_broker_api(monkeypatch):
    broker, trader, _ = _broker(monkeypatch)

    assert broker.cancel_order("123456") is True

    account, order_id = trader.cancel_calls[-1]
    assert account.account_id == "ACC123"
    assert order_id == 123456


def test_miniqmt_cancel_order_accepts_minus_one_when_query_shows_terminal(monkeypatch):
    broker, trader, xtconstant = _broker(monkeypatch)

    def cancel_fail(acc, oid):
        trader.cancel_calls.append((acc, oid))
        return -1

    trader.cancel_order_stock = cancel_fail
    trader.orders = [
        types.SimpleNamespace(
            order_id=123456,
            stock_code="000001.SZ",
            order_type=23,
            order_status=xtconstant.ORDER_CANCELED,
            status_msg="已撤",
            order_volume=100,
            price=10.0,
            traded_volume=0,
            traded_price=0.0,
            order_time=1700000000,
        )
    ]

    assert broker.cancel_order("123456") is True
    assert trader.cancel_calls


def test_miniqmt_cancel_order_accepts_minus_one_when_query_empty(monkeypatch):
    """Cancel -1 and empty query_orders => True (no live entrust rows)."""
    broker, trader, _ = _broker(monkeypatch)

    def cancel_fail(acc, oid):
        trader.cancel_calls.append((acc, oid))
        return -1

    trader.cancel_order_stock = cancel_fail
    trader.orders = []

    assert broker.cancel_order("1082165310") is True
    assert trader.cancel_calls


def test_miniqmt_cancel_order_accepts_minus_one_when_entrust_missing_from_query(
    monkeypatch,
):
    """When the target id is missing, treat cancel as success."""
    broker, trader, xtconstant = _broker(monkeypatch)

    def cancel_fail(acc, oid):
        trader.cancel_calls.append((acc, oid))
        return -1

    trader.cancel_order_stock = cancel_fail
    trader.orders = [
        types.SimpleNamespace(
            order_id=999999,
            stock_code="000001.SZ",
            order_type=23,
            order_status=xtconstant.ORDER_REPORTED,
            status_msg="已报",
            order_volume=100,
            price=10.0,
            traded_volume=0,
            traded_price=0.0,
            order_time=1700000000,
        )
    ]

    assert broker.cancel_order("1082165310") is True
    assert trader.cancel_calls


def test_miniqmt_execution_status_includes_real_fee_fields(monkeypatch):
    broker, trader, _ = _broker(monkeypatch)
    order = types.SimpleNamespace(
        order_id=123456,
        stock_code="000001.SZ",
        order_type=24,
        order_status=53,
        status_msg="已成",
        order_volume=100,
        price=10.0,
        traded_volume=100,
        traded_price=10.01,
        order_time=1700000000,
        commission=0.12,
        stamp_tax=0.5,
    )
    trader.orders = [order]

    status = broker.get_execution_status()["123456"]

    assert status["status"] == "filled"
    assert status["commission"] == 0.12
    assert status["stamp_tax"] == 0.5


def test_miniqmt_execution_status_tolerates_missing_partial_constant(monkeypatch):
    broker, trader, xtconstant = _broker(monkeypatch)
    delattr(xtconstant, "ORDER_PART_SUCCEEDED")
    trader.orders = [
        types.SimpleNamespace(
            order_id=123456,
            stock_code="000001.SZ",
            order_type=24,
            order_status=52,
            status_msg="部成",
            order_volume=100,
            price=10.0,
            traded_volume=50,
            traded_price=10.01,
            order_time=1700000000,
        )
    ]

    status = broker.get_execution_status()["123456"]

    assert status["status"] == "partial_filled"
    assert status["filled_size"] == 50
