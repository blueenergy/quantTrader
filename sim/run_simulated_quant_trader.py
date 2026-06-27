from __future__ import annotations

import os
import sys
import time

from bson import ObjectId
from pymongo import MongoClient


DEFAULT_SECURITIES_ACCOUNT_ID = "00000000000000000000e2e1"
DEFAULT_USER_ID = "sim-e2e-user"
DEFAULT_ACCOUNT_ID = "SIM-ACC-0001"
DEFAULT_BROKER = "SIMULATED_MINIQMT"


def _env_default(name: str, value: str) -> str:
    current = os.getenv(name)
    if current not in (None, ""):
        return current
    os.environ[name] = value
    return value


def _seed_simulated_account() -> None:
    if os.getenv("QUANT_TRADER_SEED_SIM_ACCOUNT", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    mongo_uri = _env_default("TRADER_MONGO_URI", "mongodb://quant-mongodb:27017/")
    mongo_db = _env_default("TRADER_MONGO_DB", os.getenv("MONGO_DB", "finance"))
    user_id = _env_default("TRADER_USER_ID", DEFAULT_USER_ID)
    account_id = _env_default("TRADER_MINIQMT_ACCOUNT_ID", DEFAULT_ACCOUNT_ID)
    securities_account_id = _env_default("TRADER_SECURITIES_ACCOUNT_ID", DEFAULT_SECURITIES_ACCOUNT_ID)

    client = MongoClient(mongo_uri)
    try:
        db = client[mongo_db]
        db.securities_accounts.update_one(
            {"_id": ObjectId(securities_account_id), "user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "broker": os.getenv("QUANT_TRADER_SIM_BROKER_NAME", DEFAULT_BROKER),
                    "account_id": account_id,
                    "is_simulated": True,
                    "updated_at": time.time(),
                },
                "$setOnInsert": {"created_at": time.time()},
            },
            upsert=True,
        )
    finally:
        client.close()


def main() -> None:
    _env_default("QUANT_TRADER_ENV", "dev")
    _env_default("TRADER_BACKEND_MODE", "db")
    _env_default("TRADER_BROKER", "miniQMT")
    _env_default("TRADER_MINIQMT_XT_PATH", "/tmp/fake-userdata-mini")
    _env_default("TRADER_POLL_INTERVAL", "1.0")
    _env_default("TRADER_LOG_LEVEL", "INFO")
    _env_default("QUANT_TRADER_SIM_AUTO_TICK", "1")

    if os.getenv("QUANT_TRADER_ENV") != "dev":
        raise RuntimeError("simulated quantTrader container requires QUANT_TRADER_ENV=dev")

    _seed_simulated_account()

    from quant_trader.cli import main as cli_main

    cli_main(sys.argv[1:])


if __name__ == "__main__":
    main()
