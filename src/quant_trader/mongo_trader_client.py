from __future__ import annotations

import copy
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection

from .config import TraderConfig

log = logging.getLogger("quantTrader")


def _serialize_doc(doc: Any) -> Any:
    """Mirror quantFinance serialize_doc for JSON-safe dicts."""

    def convert(obj: Any) -> Any:
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(i) for i in obj]
        return obj

    return convert(doc)


def _signal_sort_key(row: Dict[str, Any]) -> tuple:
    return (
        0 if str(row.get("execution_phase") or row.get("action") or "").lower() == "sell" else 1,
        int(row.get("execution_priority") or 1000),
        float(row.get("timestamp") or 0),
        str(row.get("order_id") or ""),
    )


class MongoTraderClient:
    """MongoDB-backed trader backend (mirrors :class:`TraderApiClient`).

    Uses the same collections and update semantics as ``quantFinance/routers/trader.py``.
    Requires ``TraderConfig.user_id`` and Mongo connection (no JWT).
    """

    def __init__(self, cfg: TraderConfig) -> None:
        if not cfg.mongo_uri:
            raise RuntimeError("MongoTraderClient requires TraderConfig.mongo_uri")
        if not cfg.user_id:
            raise RuntimeError("MongoTraderClient requires TraderConfig.user_id")

        self.cfg = cfg
        self.securities_account_id = cfg.securities_account_id
        self._user_id = cfg.user_id

        self._client = MongoClient(cfg.mongo_uri)
        db = self._client[cfg.mongo_db]
        self._signals: Collection = db["trade_signals"]
        self._executions: Collection = db["trade_executions"]
        self._worker_status: Collection = db["worker_status"]
        self._trader_positions: Collection = db["trader_positions"]
        self._trader_accounts: Collection = db["trader_accounts"]
        self._position_snapshots: Collection = db["position_snapshots"]
        self._securities_accounts: Collection = db["securities_accounts"]

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Signals & executions
    # ------------------------------------------------------------------
    def get_pending_signals(self, limit: int = 50, include_submitted: bool = False) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "user_id": self._user_id,
            "is_executable": True,
            "mode": "live",
        }
        if include_submitted:
            query["status"] = {"$in": ["pending", "retry_pending", "submitted", "partial_filled", "cancel_requested"]}
        else:
            query["status"] = {"$in": ["pending", "retry_pending"]}

        cursor = self._signals.find(query).sort("timestamp", 1).limit(limit)
        signals = [_serialize_doc(doc) for doc in cursor]
        signals.sort(key=_signal_sort_key)
        log.debug("DB returned %d signals (include_submitted=%s)", len(signals), include_submitted)
        return signals

    def get_submitted_signals(self, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            all_signals = self.get_pending_signals(limit=limit, include_submitted=True)
            submitted = [s for s in all_signals if s.get("status") in {"submitted", "partial_filled", "cancel_requested"}]
            log.debug("Found %d submitted signals out of %d total", len(submitted), len(all_signals))
            return submitted
        except Exception as e:  # noqa: BLE001
            log.error("Failed to fetch submitted signals: %s", e)
            return []

    def update_signal_status(self, order_id: str, payload: Dict[str, Any]) -> None:
        signal = self._signals.find_one({"order_id": order_id, "user_id": self._user_id})
        if not signal:
            raise RuntimeError(f"Signal not found: {order_id}")

        result = self._signals.update_one(
            {"order_id": order_id, "user_id": self._user_id},
            {"$set": payload},
        )
        if result.matched_count == 0:
            raise RuntimeError("Signal not found")

    def create_execution(self, execution: Dict[str, Any]) -> None:
        execution = copy.deepcopy(execution)
        user_id = self._user_id
        execution["user_id"] = user_id
        if "timestamp" not in execution:
            execution["timestamp"] = time.time()

        broker_order_id = execution.get("broker_order_id") or execution.get("qmt_order_id")
        order_id = execution.get("order_id")
        execution_status = execution.get("status") or "filled"

        signal = self._signals.find_one({"order_id": order_id, "user_id": user_id}) if order_id else None
        if signal:
            for field in ("plan_id", "strategy_template_id", "source", "securities_account_id", "account_id", "broker"):
                if signal.get(field) is not None:
                    execution.setdefault(field, signal.get(field))
        if broker_order_id:
            execution["broker_order_id"] = broker_order_id
            execution.setdefault("qmt_order_id", broker_order_id)

        execution_key: Dict[str, Any] = {
            "user_id": user_id,
            "order_id": order_id,
            "status": execution_status,
        }
        if broker_order_id:
            execution_key["broker_order_id"] = broker_order_id
        if execution.get("filled_size") is not None:
            execution_key["filled_size"] = execution.get("filled_size")

        existing = self._executions.find_one(execution_key) if order_id else None
        if existing:
            self._executions.update_one({"_id": existing["_id"]}, {"$set": execution})
        else:
            self._executions.insert_one(execution)

        if order_id:
            signal_update: Dict[str, Any] = {
                "status": execution_status,
                "updated_at": execution["timestamp"],
            }
            if execution_status in {
                "filled",
                "executed",
                "rejected",
                "cancelled",
                "canceled",
                "partial_cancelled",
                "failed",
            }:
                signal_update["executed_at"] = execution["timestamp"]
            if execution.get("filled_size") is not None:
                signal_update["filled_qty"] = execution.get("filled_size")
            if execution.get("filled_price") is not None:
                signal_update["avg_price"] = execution.get("filled_price")
            self._signals.update_one(
                {"order_id": order_id, "user_id": user_id},
                {"$set": signal_update},
            )

    # ------------------------------------------------------------------
    # Heartbeat & positions (same as trader router)
    # ------------------------------------------------------------------
    def record_heartbeat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        heartbeat = {
            "securities_account_id": self.securities_account_id,
            **payload,
        }
        now = time.time()
        worker_id = heartbeat.get("worker_id") or (
            f"quantTrader:{heartbeat.get('securities_account_id') or heartbeat.get('account_id') or self._user_id}"
        )
        doc = {
            **heartbeat,
            "worker_id": worker_id,
            "worker_type": "quantTrader",
            "user_id": self._user_id,
            "last_seen_at": now,
            "status": heartbeat.get("status") or "running",
        }
        self._worker_status.update_one(
            {"worker_id": worker_id, "user_id": self._user_id},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {"success": True, "data": _serialize_doc(doc)}

    def _resolve_securities_account(self, securities_account_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not securities_account_id:
            return None
        try:
            account_doc = self._securities_accounts.find_one(
                {"_id": ObjectId(securities_account_id), "user_id": self._user_id}
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Invalid securities_account_id: {securities_account_id}") from exc
        if not account_doc:
            raise RuntimeError(f"Securities account not found: {securities_account_id}")
        return account_doc

    def sync_positions(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        securities_account_id = self.securities_account_id
        current_time = time.time()

        account_doc = self._resolve_securities_account(securities_account_id) if securities_account_id else None

        delete_query: Dict[str, Any] = {"user_id": self._user_id}
        if securities_account_id:
            delete_query["securities_account_id"] = securities_account_id
        self._trader_positions.delete_many(delete_query)

        if positions:
            to_insert: List[Dict[str, Any]] = []
            for pos in positions:
                row = copy.deepcopy(pos)
                row["user_id"] = self._user_id
                row["synced_at"] = current_time
                if securities_account_id:
                    row["securities_account_id"] = securities_account_id
                    if account_doc and (not row.get("broker") or not row.get("account_id")):
                        row["broker"] = account_doc.get("broker")
                        row["account_id"] = account_doc.get("account_id")
                to_insert.append(row)
            self._trader_positions.insert_many(to_insert)

        return {"success": True, "synced_count": len(positions), "timestamp": current_time}

    def sync_account(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        securities_account_id = self.securities_account_id
        if not securities_account_id:
            raise RuntimeError("securities_account_id is required to prevent account conflicts")

        account_doc = self._resolve_securities_account(securities_account_id)
        current_time = time.time()

        data = copy.deepcopy(account_data)
        data["user_id"] = self._user_id
        data["synced_at"] = current_time
        data["securities_account_id"] = securities_account_id
        if not data.get("broker"):
            data["broker"] = account_doc.get("broker") if account_doc else None
        if not data.get("account_id"):
            data["account_id"] = account_doc.get("account_id") if account_doc else None

        query = {"user_id": self._user_id, "securities_account_id": securities_account_id}
        self._trader_accounts.update_one(query, {"$set": data}, upsert=True)
        return {"success": True, "timestamp": current_time}

    def store_position_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        securities_account_id = self.securities_account_id
        snap = copy.deepcopy(snapshot)
        snap["user_id"] = self._user_id

        if securities_account_id:
            account_doc = self._securities_accounts.find_one(
                {"_id": ObjectId(securities_account_id), "user_id": self._user_id}
            )
            if account_doc:
                snap["securities_account_id"] = securities_account_id
                if not snap.get("broker"):
                    snap["broker"] = account_doc.get("broker")
                if not snap.get("account_id"):
                    snap["account_id"] = account_doc.get("account_id")

        date_str = snap.get("date")
        if date_str:
            query: Dict[str, Any] = {"user_id": self._user_id, "date": date_str}
            if securities_account_id:
                query["securities_account_id"] = securities_account_id
            existing = self._position_snapshots.find_one(query)
            if existing:
                self._position_snapshots.update_one({"_id": existing["_id"]}, {"$set": snap})
                return {"success": True, "message": "Snapshot updated", "date": date_str}

        result = self._position_snapshots.insert_one(snap)
        return {"success": True, "message": "Snapshot created", "snapshot_id": str(result.inserted_id)}

    def update_position(self, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a single position (no dedicated FastAPI route; kept for API parity)."""
        row = copy.deepcopy(position_data)
        row["user_id"] = self._user_id
        if self.securities_account_id:
            row.setdefault("securities_account_id", self.securities_account_id)
        symbol = row.get("symbol")
        if not symbol:
            raise RuntimeError("position_data must include symbol")
        q: Dict[str, Any] = {"user_id": self._user_id, "symbol": symbol}
        if row.get("securities_account_id"):
            q["securities_account_id"] = row["securities_account_id"]
        self._trader_positions.update_one(q, {"$set": row}, upsert=True)
        return {"success": True}

    def cleanup_stale_positions(self, current_symbols: List[str], account_id: Optional[str] = None) -> Dict[str, Any]:
        cleanup_query: Dict[str, Any] = {
            "user_id": self._user_id,
            "symbol": {"$nin": current_symbols},
        }
        sec_id = account_id or self.securities_account_id
        if sec_id:
            cleanup_query["securities_account_id"] = sec_id
        result = self._trader_positions.delete_many(cleanup_query)
        return {"success": True, "deleted_count": result.deleted_count, "timestamp": time.time()}
