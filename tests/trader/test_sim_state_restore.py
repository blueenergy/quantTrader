from __future__ import annotations

import sys
from pathlib import Path

import mongomock


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sim.matching_engine import MARKET_PEER_PRICE_FIRST, STOCK_BUY, SimMatchingEngine
from sim.state_restore import restore_engine_from_mongo


def test_restore_state_is_idempotent_and_queries_snapshot():
    engine = SimMatchingEngine()
    positions = [
        {"symbol": "000001.SZ", "qty": 100, "can_use_volume": 80, "avg_price": 10.5},
        {"symbol": "600000.SH", "volume": 200, "can_use_volume": 0, "last_price": 8.8},
    ]

    engine.restore_state(cash=12345.0, positions=positions, next_order_id=1000123, account_id="ACC-1")
    engine.restore_state(cash=12345.0, positions=positions, next_order_id=1000123, account_id="ACC-1")

    assert engine.cash == 12345.0
    assert engine.account_id == "ACC-1"
    assert engine.next_order_id == 1000123
    queried_positions = {pos.stock_code: pos for pos in engine.query_positions()}
    assert queried_positions["000001.SZ"].volume == 100
    assert queried_positions["000001.SZ"].can_use_volume == 80
    assert queried_positions["000001.SZ"].open_price == 10.5
    assert queried_positions["600000.SH"].volume == 200
    assert queried_positions["600000.SH"].can_use_volume == 0
    asset = engine.query_asset()
    assert asset.cash == 12345.0
    assert asset.market_value == 2810.0


def test_restore_engine_from_mongo_loads_cash_positions_and_next_order_id():
    client = mongomock.MongoClient()
    db = client["finance"]
    db.trader_accounts.insert_one(
        {
            "user_id": "user-1",
            "securities_account_id": "sec-1",
            "account_id": "ACC-1",
            "cash": 45678.0,
            "synced_at": 10,
        }
    )
    db.trader_positions.insert_many(
        [
            {
                "user_id": "user-1",
                "securities_account_id": "sec-1",
                "symbol": "000001.SZ",
                "qty": 100,
                "can_use_volume": 90,
                "avg_price": 11.0,
            },
            {
                "user_id": "user-1",
                "securities_account_id": "sec-1",
                "symbol": "000002.SZ",
                "shares": 200,
                "available_qty": 180,
                "cost_price": 12.0,
            },
        ]
    )
    db.trade_signals.insert_one(
        {"user_id": "user-1", "securities_account_id": "sec-1", "qmt_order_id": "1000100"}
    )
    db.trade_executions.insert_one(
        {"user_id": "user-1", "securities_account_id": "sec-1", "broker_order_id": "1000105"}
    )
    db.trade_signals.insert_one(
        {"user_id": "user-1", "securities_account_id": "other", "qmt_order_id": "1000999"}
    )
    engine = SimMatchingEngine()

    summary = restore_engine_from_mongo(
        engine,
        db,
        user_id="user-1",
        securities_account_id="sec-1",
        account_id="ACC-ENV",
    )

    assert summary["restored_positions"] == 2
    assert engine.cash == 45678.0
    assert engine.account_id == "ACC-ENV"
    assert engine.next_order_id == 1000106
    assert {pos.stock_code: pos.volume for pos in engine.query_positions()} == {
        "000001.SZ": 100,
        "000002.SZ": 200,
    }
    next_order_id = engine.place_order("000003.SZ", STOCK_BUY, 100, MARKET_PEER_PRICE_FIRST, 10.0)
    assert next_order_id == 1000106
    assert engine.next_order_id == 1000107


def test_restore_engine_from_mongo_falls_back_without_snapshots():
    client = mongomock.MongoClient()
    engine = SimMatchingEngine(initial_cash=999.0, account_id="DEFAULT")

    summary = restore_engine_from_mongo(
        engine,
        client["finance"],
        user_id="user-1",
        securities_account_id="sec-1",
    )

    assert summary["restored_positions"] == 0
    assert summary["account_snapshot_found"] is False
    assert engine.cash == 999.0
    assert engine.next_order_id == 1_000_001
    assert engine.account_id == "DEFAULT"
    assert engine.query_positions() == []
