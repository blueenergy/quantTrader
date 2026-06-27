from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

import mongomock
import pytest
from bson import ObjectId

from quant_trader.config import TraderConfig
from quant_trader.mongo_trader_client import MongoTraderClient
from quant_trader.trader_loop import TraderLoop
from sim.matching_engine import default_registry


SIM_USER_ID = "sim-e2e-user"
SIM_BROKER_NAME = "SIMULATED_MINIQMT"


@dataclass
class AccountLoop:
    account_id: str
    securities_account_id: str
    api: MongoTraderClient
    broker: Any
    loop: TraderLoop


@pytest.fixture
def multi_account_context(monkeypatch, install_fake_xtquant, sim_engine):
    monkeypatch.delenv("QUANT_TRADER_SIM_AUTO_TICK", raising=False)
    mongo_uri = "mongodb://mongomock"
    db_name = f"finance_e2e_multi_{uuid.uuid4().hex}"
    client = mongomock.MongoClient()
    monkeypatch.setattr("quant_trader.mongo_trader_client.MongoClient", lambda *_args, **_kwargs: client)
    db = client[db_name]

    from quant_trader.broker_miniQMT import MiniQMTBroker

    accounts: List[AccountLoop] = []
    try:
        for index, account_id in enumerate(("SIM-ACC-A", "SIM-ACC-B"), start=1):
            securities_account_id = str(ObjectId())
            db.securities_accounts.insert_one(
                {
                    "_id": ObjectId(securities_account_id),
                    "user_id": SIM_USER_ID,
                    "broker": SIM_BROKER_NAME,
                    "account_id": account_id,
                    "created_at": time.time(),
                }
            )
            cfg = TraderConfig(
                backend_mode="db",
                mongo_uri=mongo_uri,
                mongo_db=db_name,
                user_id=SIM_USER_ID,
                securities_account_id=securities_account_id,
                broker="miniQMT",
                miniQMT={"xt_path": "/fake/userdata_mini", "account_id": account_id},
                poll_interval=0.01,
                trading_sessions="",
                use_activate_after=False,
            )
            api = MongoTraderClient(cfg)
            broker = MiniQMTBroker(xt_path=cfg.miniQMT["xt_path"], account_id=cfg.miniQMT["account_id"])
            loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_position_sync=True, enable_execution_tracking=True)
            if loop.position_manager:
                loop.position_manager.sync_interval = 0.0
            accounts.append(
                AccountLoop(
                    account_id=account_id,
                    securities_account_id=securities_account_id,
                    api=api,
                    broker=broker,
                    loop=loop,
                )
            )

        yield db, accounts
    finally:
        for account in accounts:
            account.broker.close()
            account.api.close()


def _seed_signal(db: Any, account: AccountLoop, **overrides: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "order_id": overrides.pop("order_id"),
        "user_id": SIM_USER_ID,
        "symbol": overrides.pop("symbol"),
        "action": overrides.pop("action", "buy"),
        "size": overrides.pop("size", 100),
        "price": overrides.pop("price", 10.0),
        "reference_price": overrides.pop("reference_price", 10.0),
        "status": overrides.pop("status", "pending"),
        "is_executable": overrides.pop("is_executable", True),
        "mode": overrides.pop("mode", "live"),
        "timestamp": overrides.pop("timestamp", time.time()),
        "securities_account_id": account.securities_account_id,
        "account_id": account.account_id,
        "broker": SIM_BROKER_NAME,
    }
    row.update(overrides)
    db.trade_signals.insert_one(row)
    return row


@pytest.mark.e2e
def test_two_accounts_positions_are_isolated(multi_account_context):
    db, accounts = multi_account_context
    account_a, account_b = accounts
    _seed_signal(db, account_a, order_id="SIM-A-BUY", symbol="000001.SZ", size=100, price=10.0)
    _seed_signal(db, account_b, order_id="SIM-B-BUY", symbol="000002.SZ", size=200, price=20.0)

    account_a.loop.run_iteration()
    account_b.loop.run_iteration()
    default_registry.get(account_a.account_id).tick()
    default_registry.get(account_b.account_id).tick()
    account_a.loop.run_iteration()
    account_b.loop.run_iteration()

    position_a = db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_a.securities_account_id, "symbol": "000001.SZ"}
    )
    position_b = db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_b.securities_account_id, "symbol": "000002.SZ"}
    )
    assert position_a is not None
    assert position_a["qty"] == 100
    assert position_b is not None
    assert position_b["qty"] == 200
    assert db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_a.securities_account_id, "symbol": "000002.SZ"}
    ) is None
    assert db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_b.securities_account_id, "symbol": "000001.SZ"}
    ) is None

    account_snapshot_a = db.trader_accounts.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_a.securities_account_id}
    )
    account_snapshot_b = db.trader_accounts.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_b.securities_account_id}
    )
    assert account_snapshot_a["cash"] == 999000.0
    assert account_snapshot_b["cash"] == 996000.0


@pytest.mark.e2e
def test_two_accounts_same_symbol_are_isolated(multi_account_context):
    db, accounts = multi_account_context
    account_a, account_b = accounts
    _seed_signal(db, account_a, order_id="SIM-A-SAME-SYMBOL", symbol="000001.SZ", size=100, price=10.0)
    _seed_signal(db, account_b, order_id="SIM-B-SAME-SYMBOL", symbol="000001.SZ", size=300, price=10.0)

    account_a.loop.run_iteration()
    account_b.loop.run_iteration()
    default_registry.get(account_a.account_id).tick()
    default_registry.get(account_b.account_id).tick()
    account_a.loop.run_iteration()
    account_b.loop.run_iteration()

    position_a = db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_a.securities_account_id, "symbol": "000001.SZ"}
    )
    position_b = db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "securities_account_id": account_b.securities_account_id, "symbol": "000001.SZ"}
    )

    assert position_a is not None
    assert position_a["qty"] == 100
    assert position_b is not None
    assert position_b["qty"] == 300
