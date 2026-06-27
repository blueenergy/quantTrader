from __future__ import annotations

import os
import sys
import time
import logging
from typing import Dict, List

from bson import ObjectId
from pymongo import MongoClient


log = logging.getLogger(__name__)

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


def _single_account_spec() -> Dict[str, str]:
    return {
        "account_id": _env_default("TRADER_MINIQMT_ACCOUNT_ID", DEFAULT_ACCOUNT_ID),
        "securities_account_id": _env_default("TRADER_SECURITIES_ACCOUNT_ID", DEFAULT_SECURITIES_ACCOUNT_ID),
    }


def _multi_account_specs() -> List[Dict[str, str]]:
    """Parse optional multi-account simulation mapping.

    Format: TRADER_SECURITIES_ACCOUNT_IDS=sec_id_1:account_id_1,sec_id_2:account_id_2
    """

    raw = os.getenv("TRADER_SECURITIES_ACCOUNT_IDS", "").strip()
    if not raw:
        return []

    specs: List[Dict[str, str]] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                "TRADER_SECURITIES_ACCOUNT_IDS entries must use securities_account_id:account_id"
            )
        securities_account_id, account_id = [part.strip() for part in item.split(":", 1)]
        if not securities_account_id or not account_id:
            raise ValueError(
                "TRADER_SECURITIES_ACCOUNT_IDS entries must include both securities_account_id and account_id"
            )
        specs.append({"securities_account_id": securities_account_id, "account_id": account_id})
    return specs


def _account_specs() -> List[Dict[str, str]]:
    specs = _multi_account_specs()
    return specs if specs else [_single_account_spec()]


def _seed_account_doc(db, *, user_id: str, account_id: str, securities_account_id: str) -> None:
    db.securities_accounts.update_one(
        {"_id": ObjectId(securities_account_id), "user_id": user_id},
        {
            "$set": {
                "is_simulated": True,
                "updated_at": time.time(),
            },
            "$setOnInsert": {
                "user_id": user_id,
                "broker": os.getenv("QUANT_TRADER_SIM_BROKER_NAME", DEFAULT_BROKER),
                "account_id": account_id,
                "created_at": time.time(),
            },
        },
        upsert=True,
    )


def _seed_simulated_account() -> None:
    if os.getenv("QUANT_TRADER_SEED_SIM_ACCOUNT", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    mongo_uri = _env_default("TRADER_MONGO_URI", "mongodb://quant-mongodb:27017/")
    mongo_db = _env_default("TRADER_MONGO_DB", os.getenv("MONGO_DB", "finance"))
    user_id = _env_default("TRADER_USER_ID", DEFAULT_USER_ID)
    account_specs = _account_specs()

    client = MongoClient(mongo_uri)
    try:
        db = client[mongo_db]
        for account in account_specs:
            _seed_account_doc(db, user_id=user_id, **account)
    finally:
        client.close()


def _restore_sim_engine_from_mongo() -> None:
    if os.getenv("QUANT_TRADER_SIM_RESTORE_STATE", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    mongo_uri = _env_default("TRADER_MONGO_URI", "mongodb://quant-mongodb:27017/")
    mongo_db = _env_default("TRADER_MONGO_DB", os.getenv("MONGO_DB", "finance"))
    user_id = _env_default("TRADER_USER_ID", DEFAULT_USER_ID)
    account_specs = _account_specs()

    client = MongoClient(mongo_uri)
    try:
        from sim.matching_engine import default_engine, default_registry
        from sim.state_restore import restore_engine_from_mongo, restore_registry_from_mongo

        if _multi_account_specs():
            summaries = restore_registry_from_mongo(
                default_registry,
                client[mongo_db],
                user_id=user_id,
                accounts=account_specs,
            )
            for summary in summaries.values():
                log.info(
                    "Restored simulated miniQMT state: positions=%s cash=%.2f next_order_id=%s account_id=%s",
                    summary["restored_positions"],
                    summary["cash"],
                    summary["next_order_id"],
                    summary["account_id"],
                )
        else:
            summary = restore_engine_from_mongo(
                default_engine,
                client[mongo_db],
                user_id=user_id,
                securities_account_id=account_specs[0]["securities_account_id"],
                account_id=account_specs[0]["account_id"],
            )
            default_registry.register(default_engine)
            log.info(
                "Restored simulated miniQMT state: positions=%s cash=%.2f next_order_id=%s account_id=%s",
                summary["restored_positions"],
                summary["cash"],
                summary["next_order_id"],
                summary["account_id"],
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to restore simulated miniQMT state from Mongo: %s", exc)
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
    _env_default("QUANT_TRADER_SIM_RESTORE_STATE", "1")

    if os.getenv("QUANT_TRADER_ENV") != "dev":
        raise RuntimeError("simulated quantTrader container requires QUANT_TRADER_ENV=dev")

    _seed_simulated_account()
    _restore_sim_engine_from_mongo()

    from quant_trader.cli import main as cli_main

    cli_main(sys.argv[1:])


if __name__ == "__main__":
    main()
