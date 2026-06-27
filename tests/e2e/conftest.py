from __future__ import annotations

import importlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import mongomock
import pytest
from bson import ObjectId

# CI installs the package from ``src``; keep top-level dev-only ``sim`` importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_trader.config import TraderConfig
from quant_trader.mongo_trader_client import MongoTraderClient
from quant_trader.trader_loop import TraderLoop
from sim.matching_engine import default_engine


SIM_USER_ID = "sim-e2e-user"
SIM_ACCOUNT_ID = "SIM-ACC-0001"
SIM_BROKER_NAME = "SIMULATED_MINIQMT"


@dataclass
class E2EContext:
    cfg: TraderConfig
    db: Any
    loop: TraderLoop
    engine: Any
    securities_account_id: str


@pytest.fixture
def install_fake_xtquant(monkeypatch):
    monkeypatch.setenv("QUANT_TRADER_ENV", "dev")
    xtquant = importlib.import_module("sim.fake_xtquant.xtquant")
    xttrader = importlib.import_module("sim.fake_xtquant.xtquant.xttrader")
    xttype = importlib.import_module("sim.fake_xtquant.xtquant.xttype")
    xtconstant = importlib.import_module("sim.fake_xtquant.xtquant.xtconstant")
    monkeypatch.setitem(sys.modules, "xtquant", xtquant)
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader)
    monkeypatch.setitem(sys.modules, "xtquant.xttype", xttype)
    monkeypatch.setitem(sys.modules, "xtquant.xtconstant", xtconstant)
    return xtquant


@pytest.fixture
def sim_engine():
    default_engine.reset()
    return default_engine


@pytest.fixture
def e2e_context(monkeypatch, install_fake_xtquant, sim_engine):
    client = mongomock.MongoClient()
    monkeypatch.setattr("quant_trader.mongo_trader_client.MongoClient", lambda *_args, **_kwargs: client)
    db_name = "finance_e2e"
    db = client[db_name]
    securities_account_id = str(ObjectId())
    db.securities_accounts.insert_one(
        {
            "_id": ObjectId(securities_account_id),
            "user_id": SIM_USER_ID,
            "broker": SIM_BROKER_NAME,
            "account_id": SIM_ACCOUNT_ID,
            "created_at": time.time(),
        }
    )

    cfg = TraderConfig(
        backend_mode="db",
        mongo_uri="mongodb://mongomock",
        mongo_db=db_name,
        user_id=SIM_USER_ID,
        securities_account_id=securities_account_id,
        broker="miniQMT",
        miniQMT={"xt_path": "/fake/userdata_mini", "account_id": SIM_ACCOUNT_ID},
        poll_interval=0.01,
        trading_sessions="",
        use_activate_after=False,
    )
    api = MongoTraderClient(cfg)

    from quant_trader.broker_miniQMT import MiniQMTBroker

    broker = MiniQMTBroker(xt_path=cfg.miniQMT["xt_path"], account_id=cfg.miniQMT["account_id"])
    loop = TraderLoop(cfg=cfg, api=api, broker=broker, enable_position_sync=True, enable_execution_tracking=True)
    if loop.position_manager:
        loop.position_manager.sync_interval = 0.0

    try:
        yield E2EContext(
            cfg=cfg,
            db=db,
            loop=loop,
            engine=sim_engine,
            securities_account_id=securities_account_id,
        )
    finally:
        broker.close()
        api.close()


@pytest.fixture
def seed_signal(e2e_context):
    def _seed_signal(**overrides: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "order_id": overrides.pop("order_id", "SIM-BUY-001"),
            "user_id": SIM_USER_ID,
            "symbol": overrides.pop("symbol", "000001.SZ"),
            "action": overrides.pop("action", "buy"),
            "size": overrides.pop("size", 100),
            "price": overrides.pop("price", 10.0),
            "reference_price": overrides.pop("reference_price", 10.0),
            "status": overrides.pop("status", "pending"),
            "is_executable": overrides.pop("is_executable", True),
            "mode": overrides.pop("mode", "live"),
            "timestamp": overrides.pop("timestamp", time.time()),
            "securities_account_id": e2e_context.securities_account_id,
            "account_id": SIM_ACCOUNT_ID,
            "broker": SIM_BROKER_NAME,
        }
        row.update(overrides)
        e2e_context.db.trade_signals.insert_one(row)
        return row

    return _seed_signal
