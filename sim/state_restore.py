from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


def restore_engine_from_mongo(
    engine: Any,
    db: Any,
    *,
    user_id: str,
    securities_account_id: str,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore fake miniQMT state from existing Mongo snapshots.

    This first-stage provider rebuilds the durable account snapshot from
    ``trader_accounts`` and ``trader_positions``. It deliberately does not
    restore active submitted orders; full mid-order recovery belongs to the
    future ``quant_trader_sim_states`` provider.
    """

    account = _latest_account_snapshot(db, user_id=user_id, securities_account_id=securities_account_id)
    positions = list(_position_snapshots(db, user_id=user_id, securities_account_id=securities_account_id))
    next_order_id = _next_order_id(db, user_id=user_id, securities_account_id=securities_account_id)

    cash = _optional_float((account or {}).get("cash"))
    if cash is None:
        cash = _optional_float((account or {}).get("available_cash"))

    resolved_account_id = account_id or (account or {}).get("account_id")
    engine.restore_state(
        cash=cash,
        positions=positions,
        next_order_id=next_order_id,
        account_id=resolved_account_id,
    )

    return {
        "restored_positions": len([row for row in positions if _position_quantity(row) > 0]),
        "cash": engine.cash,
        "next_order_id": engine.next_order_id,
        "account_id": engine.account_id,
        "account_snapshot_found": account is not None,
    }


def restore_registry_from_mongo(
    registry: Any,
    db: Any,
    *,
    user_id: str,
    accounts: Iterable[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Restore multiple fake miniQMT accounts into an engine registry."""

    summaries: Dict[str, Dict[str, Any]] = {}
    for account in accounts:
        securities_account_id = str(account.get("securities_account_id") or "").strip()
        account_id = str(account.get("account_id") or "").strip()
        if not securities_account_id or not account_id:
            continue

        engine = registry.get(account_id)
        summary = restore_engine_from_mongo(
            engine,
            db,
            user_id=user_id,
            securities_account_id=securities_account_id,
            account_id=account_id,
        )
        summaries[account_id] = summary
    return summaries


def _latest_account_snapshot(db: Any, *, user_id: str, securities_account_id: str) -> Optional[Dict[str, Any]]:
    return db.trader_accounts.find_one(
        {"user_id": user_id, "securities_account_id": securities_account_id},
        sort=[("synced_at", -1), ("updated_at", -1), ("_id", -1)],
    )


def _position_snapshots(db: Any, *, user_id: str, securities_account_id: str) -> Iterable[Dict[str, Any]]:
    return db.trader_positions.find({"user_id": user_id, "securities_account_id": securities_account_id})


def _next_order_id(db: Any, *, user_id: str, securities_account_id: str) -> int:
    max_order_id = 1_000_000
    signal_query = {"user_id": user_id, "securities_account_id": securities_account_id}
    for row in db.trade_signals.find(signal_query, {"qmt_order_id": 1, "broker_order_id": 1}):
        max_order_id = max(max_order_id, _order_id_value(row.get("qmt_order_id")), _order_id_value(row.get("broker_order_id")))

    execution_query = {"user_id": user_id, "securities_account_id": securities_account_id}
    for row in db.trade_executions.find(execution_query, {"broker_order_id": 1, "qmt_order_id": 1}):
        max_order_id = max(max_order_id, _order_id_value(row.get("broker_order_id")), _order_id_value(row.get("qmt_order_id")))

    return max(max_order_id + 1, 1_000_001)


def _order_id_value(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_quantity(row: Dict[str, Any]) -> int:
    for key in ("volume", "qty", "quantity", "shares"):
        if row.get(key) is not None:
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0
    return 0
