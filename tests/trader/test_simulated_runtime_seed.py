from __future__ import annotations

import importlib
import sys
from pathlib import Path

import mongomock
from bson import ObjectId


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_seed_simulated_account_preserves_existing_broker_and_account(monkeypatch):
    monkeypatch.setenv("QUANT_TRADER_ENV", "dev")
    monkeypatch.setenv("QUANT_TRADER_SEED_SIM_ACCOUNT", "1")
    monkeypatch.setenv("TRADER_MONGO_URI", "mongodb://mongomock")
    monkeypatch.setenv("TRADER_MONGO_DB", "finance")
    monkeypatch.setenv("TRADER_USER_ID", "user-1")
    monkeypatch.setenv("TRADER_SECURITIES_ACCOUNT_ID", "000000000000000000000001")
    monkeypatch.setenv("TRADER_MINIQMT_ACCOUNT_ID", "SIM-ACC-0001")
    monkeypatch.setenv("QUANT_TRADER_SIM_BROKER_NAME", "SIMULATED_MINIQMT")

    module = importlib.import_module("sim.run_simulated_quant_trader")
    client = mongomock.MongoClient()
    db = client["finance"]
    db.securities_accounts.insert_one(
        {
            "_id": ObjectId("000000000000000000000001"),
            "user_id": "user-1",
            "broker": "REAL_BROKER",
            "account_id": "62666676",
        }
    )
    monkeypatch.setattr(module, "MongoClient", lambda *_args, **_kwargs: client)

    module._seed_simulated_account()

    account = db.securities_accounts.find_one({"_id": ObjectId("000000000000000000000001")})
    assert account["broker"] == "REAL_BROKER"
    assert account["account_id"] == "62666676"
    assert account["is_simulated"] is True


def test_seed_simulated_account_sets_defaults_on_insert(monkeypatch):
    monkeypatch.setenv("QUANT_TRADER_ENV", "dev")
    monkeypatch.setenv("QUANT_TRADER_SEED_SIM_ACCOUNT", "1")
    monkeypatch.setenv("TRADER_MONGO_URI", "mongodb://mongomock")
    monkeypatch.setenv("TRADER_MONGO_DB", "finance")
    monkeypatch.setenv("TRADER_USER_ID", "user-1")
    monkeypatch.setenv("TRADER_SECURITIES_ACCOUNT_ID", "000000000000000000000002")
    monkeypatch.setenv("TRADER_MINIQMT_ACCOUNT_ID", "SIM-ACC-0002")
    monkeypatch.setenv("QUANT_TRADER_SIM_BROKER_NAME", "SIMULATED_MINIQMT")

    module = importlib.import_module("sim.run_simulated_quant_trader")
    client = mongomock.MongoClient()
    db = client["finance"]
    monkeypatch.setattr(module, "MongoClient", lambda *_args, **_kwargs: client)

    module._seed_simulated_account()

    account = db.securities_accounts.find_one({"_id": ObjectId("000000000000000000000002")})
    assert account["broker"] == "SIMULATED_MINIQMT"
    assert account["account_id"] == "SIM-ACC-0002"
    assert account["is_simulated"] is True
