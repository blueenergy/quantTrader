from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TraderConfig:
    """Configuration for quantTrader.

    api_base_url: Base URL of backend API, e.g. "http://backend:8000/api"
    api_token:   Bearer token for authentication
    poll_interval: Seconds between each polling cycle
    log_level:     Logging level string, e.g. "INFO", "DEBUG"
    broker:        Broker type: "simulated" or "miniQMT"
    miniQMT:       miniQMT broker config (if broker="miniQMT")
    """

    api_base_url: str
    api_token: str
    poll_interval: float = 1.0
    log_level: str = "INFO"
    broker: str = "simulated"
    miniQMT: Optional[Dict[str, Any]] = field(default_factory=dict)


def load_config(config_path: str | None = None) -> TraderConfig:
    """Load configuration from JSON file and environment variables.

    Priority:
    1. JSON file (if provided)
    2. Environment variables

    Required:
    - api_base_url  (TRADER_API_BASE_URL or config.api_base_url)
    - api_token     (TRADER_API_TOKEN or config.api_token)
    """
    data: dict[str, object] = {}
    if config_path:
        p = Path(config_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))

    api_base_url = (data.get("api_base_url") if isinstance(data.get("api_base_url"), str) else None) or os.getenv(
        "TRADER_API_BASE_URL"
    )
    api_token = (data.get("api_token") if isinstance(data.get("api_token"), str) else None) or os.getenv(
        "TRADER_API_TOKEN"
    )

    if not api_base_url:
        raise RuntimeError("api_base_url is required (config.api_base_url or TRADER_API_BASE_URL)")
    if not api_token:
        raise RuntimeError("api_token is required (config.api_token or TRADER_API_TOKEN)")

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
    
    miniQMT = data.get("miniQMT") if isinstance(data.get("miniQMT"), dict) else {}

    return TraderConfig(
        api_base_url=str(api_base_url).rstrip("/"),
        api_token=str(api_token),
        poll_interval=poll_interval,
        log_level=str(log_level),
        broker=str(broker),
        miniQMT=miniQMT,
    )
