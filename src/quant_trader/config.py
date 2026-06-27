from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TraderConfig:
    """Configuration for quantTrader.

    backend_mode: ``db`` (MongoDB direct) or ``api`` (REST to quantFinance).

    DB mode (default):
    - mongo_uri, mongo_db, user_id are required.
    - api_base_url / api_token optional (e.g. for switching to API mode).

    API mode:
    - api_base_url, api_token required (same as before).

    poll_interval: Seconds between each polling cycle
    log_level: Logging level string, e.g. "INFO", "DEBUG"
    broker: Broker type: "simulated" or "miniQMT"
    miniQMT: miniQMT broker config (if broker="miniQMT")
    securities_account_id: MongoDB _id linking to securities_accounts collection

    Optional ``execution`` object in JSON (see README): buy/cancel tuning.
    Environment variables with the same semantics override JSON values.
    """

    backend_mode: str = "db"
    mongo_uri: Optional[str] = None
    mongo_db: str = "finance"
    user_id: Optional[str] = None
    api_fallback_enabled: bool = False

    api_base_url: str = ""
    api_token: str = ""
    poll_interval: float = 1.0
    log_level: str = "INFO"
    broker: str = "simulated"
    miniQMT: Optional[Dict[str, Any]] = field(default_factory=dict)
    securities_account_id: Optional[str] = None
    fee_model: Dict[str, Any] = field(default_factory=dict)
    # Execution lifecycle (env overrides JSON; see load_config)
    buy_order_timeout_seconds: float = 3600.0
    cancel_retry_grace_seconds: float = 15.0
    cancel_retry_interval_seconds: float = 25.0
    trading_sessions: str = ""
    reject_signals_outside_session: bool = False
    use_activate_after: bool = True
    sell_barrier_mode: str = "off"
    sell_barrier_timeout_seconds: float = 0.0


def _execution_float(
    exec_data: Dict[str, Any],
    json_key: str,
    env_name: str,
    default: float,
) -> float:
    """Resolve execution tuning: environment overrides JSON, then defaults."""
    ev = os.getenv(env_name)
    if ev not in (None, ""):
        try:
            return float(ev)
        except ValueError:
            pass
    if json_key in exec_data and exec_data[json_key] is not None:
        try:
            return float(exec_data[json_key])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    return default


def _execution_bool(
    exec_data: Dict[str, Any],
    json_key: str,
    env_name: str,
    default: bool,
) -> bool:
    """Resolve boolean execution tuning: environment overrides JSON."""

    raw = os.getenv(env_name)
    if raw in (None, ""):
        raw = exec_data.get(json_key) if json_key in exec_data else None
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _execution_string(
    exec_data: Dict[str, Any],
    json_key: str,
    env_name: str,
    default: str = "",
) -> str:
    """Resolve string execution tuning: environment overrides JSON."""

    if env_name in os.environ:
        return str(os.environ[env_name])
    raw = exec_data.get(json_key) if json_key in exec_data else None
    if raw in (None, ""):
        return default
    return str(raw)


def load_config(config_path: str | None = None) -> TraderConfig:
    """Load configuration from JSON file and environment variables.

    Priority:
    1. JSON file (if provided)
    2. Environment variables

    ``TRADER_BACKEND_MODE`` / ``backend_mode``: ``db`` (default) or ``api``.

    DB mode requires:
    - mongo_uri: ``mongo_uri`` in JSON, or ``TRADER_MONGO_URI`` / ``MONGO_URI``
    - mongo_db: ``mongo_db`` in JSON, or ``TRADER_MONGO_DB`` / ``MONGO_DB`` (default finance)
    - user_id: ``user_id`` in JSON, or ``TRADER_USER_ID``

    API mode requires:
    - api_base_url (``TRADER_API_BASE_URL`` or config)
    - api_token (``TRADER_API_TOKEN`` or config)
    """
    data: dict[str, object] = {}
    if config_path:
        p = Path(config_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))

    backend_raw = (
        data.get("backend_mode")
        if isinstance(data.get("backend_mode"), str)
        else os.getenv("TRADER_BACKEND_MODE", "db")
    )
    backend_mode = str(backend_raw).strip().lower() or "db"
    if backend_mode not in ("db", "api"):
        raise RuntimeError(f"Invalid backend_mode {backend_raw!r}; expected 'db' or 'api'")

    api_fallback_raw = data.get("api_fallback_enabled") if "api_fallback_enabled" in data else os.getenv(
        "TRADER_API_FALLBACK_ENABLED"
    )
    api_fallback_enabled = str(api_fallback_raw).lower() in ("1", "true", "yes") if api_fallback_raw else False

    mongo_uri = (
        (data.get("mongo_uri") if isinstance(data.get("mongo_uri"), str) else None)
        or os.getenv("TRADER_MONGO_URI")
        or os.getenv("MONGO_URI")
    )
    mongo_db = (
        (data.get("mongo_db") if isinstance(data.get("mongo_db"), str) else None)
        or os.getenv("TRADER_MONGO_DB")
        or os.getenv("MONGO_DB")
        or "finance"
    )
    user_id = (
        (data.get("user_id") if isinstance(data.get("user_id"), str) else None)
        or os.getenv("TRADER_USER_ID")
    )

    api_base_url = (data.get("api_base_url") if isinstance(data.get("api_base_url"), str) else None) or os.getenv(
        "TRADER_API_BASE_URL"
    )
    api_token = (data.get("api_token") if isinstance(data.get("api_token"), str) else None) or os.getenv(
        "TRADER_API_TOKEN"
    )

    if backend_mode == "api":
        if not api_base_url:
            raise RuntimeError("api_base_url is required in API mode (config.api_base_url or TRADER_API_BASE_URL)")
        if not api_token:
            raise RuntimeError("api_token is required in API mode (config.api_token or TRADER_API_TOKEN)")
    else:
        if not mongo_uri:
            raise RuntimeError(
                "mongo_uri is required in DB mode (config.mongo_uri, TRADER_MONGO_URI, or MONGO_URI). "
                "Set TRADER_BACKEND_MODE=api to use REST only."
            )
        if not user_id:
            raise RuntimeError(
                "user_id is required in DB mode (config.user_id or TRADER_USER_ID). "
                "Set TRADER_BACKEND_MODE=api to use token-based REST instead."
            )
        api_base_url = api_base_url or ""
        api_token = api_token or ""

    poll_interval_raw = data.get("poll_interval") if "poll_interval" in data else os.getenv("TRADER_POLL_INTERVAL")
    try:
        poll_interval = float(poll_interval_raw) if poll_interval_raw is not None else 1.0
    except (TypeError, ValueError):
        poll_interval = 1.0

    log_level = (
        data.get("log_level")
        if isinstance(data.get("log_level"), str)
        else os.getenv("TRADER_LOG_LEVEL", "INFO")
    )

    broker = (
        data.get("broker")
        if isinstance(data.get("broker"), str)
        else os.getenv("TRADER_BROKER", "simulated")
    )

    miniQMT = dict(data.get("miniQMT")) if isinstance(data.get("miniQMT"), dict) else {}
    miniqmt_xt_path = os.getenv("TRADER_MINIQMT_XT_PATH")
    miniqmt_account_id = os.getenv("TRADER_MINIQMT_ACCOUNT_ID")
    if miniqmt_xt_path:
        miniQMT["xt_path"] = miniqmt_xt_path
    if miniqmt_account_id:
        miniQMT["account_id"] = miniqmt_account_id

    securities_account_id = (
        data.get("securities_account_id")
        if isinstance(data.get("securities_account_id"), str)
        else os.getenv("TRADER_SECURITIES_ACCOUNT_ID")
    )
    fee_model = data.get("fee_model") if isinstance(data.get("fee_model"), dict) else {}
    for env_name, field_name in (
        ("TRADER_BUY_COMMISSION_RATE", "buy_commission_rate"),
        ("TRADER_SELL_COMMISSION_RATE", "sell_commission_rate"),
        ("TRADER_MIN_COMMISSION", "min_commission"),
        ("TRADER_STAMP_TAX_RATE", "stamp_tax_rate"),
        ("TRADER_TRANSFER_FEE_RATE", "transfer_fee_rate"),
        ("TRADER_TRANSACTION_COST", "transaction_cost"),
    ):
        value = os.getenv(env_name)
        if value not in (None, ""):
            fee_model[field_name] = value

    exec_data = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    buy_order_timeout_seconds = _execution_float(
        exec_data,
        "buy_order_timeout_seconds",
        "QUANT_TRADER_BUY_ORDER_TIMEOUT_SECONDS",
        3600.0,
    )
    cancel_retry_grace_seconds = _execution_float(
        exec_data,
        "cancel_retry_grace_seconds",
        "QUANT_TRADER_CANCEL_RETRY_GRACE_SECONDS",
        15.0,
    )
    cancel_retry_interval_seconds = _execution_float(
        exec_data,
        "cancel_retry_interval_seconds",
        "QUANT_TRADER_CANCEL_RETRY_INTERVAL_SECONDS",
        25.0,
    )
    trading_sessions = _execution_string(
        exec_data,
        "trading_sessions",
        "QUANT_TRADER_TRADING_SESSIONS",
        "CN_A" if str(broker).strip().lower() == "miniqmt" else "",
    )
    reject_signals_outside_session = _execution_bool(
        exec_data,
        "reject_signals_outside_session",
        "QUANT_TRADER_REJECT_SIGNALS_OUTSIDE_SESSION",
        False,
    )
    use_activate_after = _execution_bool(
        exec_data,
        "use_activate_after",
        "QUANT_TRADER_USE_ACTIVATE_AFTER",
        True,
    )
    sell_barrier_mode = _execution_string(
        exec_data,
        "sell_barrier_mode",
        "QUANT_TRADER_SELL_BARRIER_MODE",
        "off",
    ).strip().lower()
    if sell_barrier_mode not in {"off", "soft", "hard"}:
        sell_barrier_mode = "off"
    sell_barrier_timeout_seconds = _execution_float(
        exec_data,
        "sell_barrier_timeout_seconds",
        "QUANT_TRADER_SELL_BARRIER_TIMEOUT_SECONDS",
        0.0,
    )

    return TraderConfig(
        backend_mode=backend_mode,
        mongo_uri=mongo_uri,
        mongo_db=str(mongo_db),
        user_id=user_id,
        api_fallback_enabled=api_fallback_enabled,
        api_base_url=str(api_base_url).rstrip("/") if api_base_url else "",
        api_token=str(api_token) if api_token else "",
        poll_interval=poll_interval,
        log_level=str(log_level),
        broker=str(broker),
        miniQMT=miniQMT,
        securities_account_id=securities_account_id,
        fee_model=fee_model,
        buy_order_timeout_seconds=buy_order_timeout_seconds,
        cancel_retry_grace_seconds=cancel_retry_grace_seconds,
        cancel_retry_interval_seconds=cancel_retry_interval_seconds,
        trading_sessions=trading_sessions,
        reject_signals_outside_session=reject_signals_outside_session,
        use_activate_after=use_activate_after,
        sell_barrier_mode=sell_barrier_mode,
        sell_barrier_timeout_seconds=max(0.0, sell_barrier_timeout_seconds),
    )
