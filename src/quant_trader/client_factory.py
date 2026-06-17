from __future__ import annotations

from typing import Union

from .api_client import TraderApiClient
from .config import TraderConfig
from .mongo_trader_client import MongoTraderClient


def create_trader_client(cfg: TraderConfig) -> Union[TraderApiClient, MongoTraderClient]:
    """Instantiate REST or MongoDB trader backend from ``TraderConfig``."""
    mode = (cfg.backend_mode or "db").strip().lower()
    if mode == "api":
        return TraderApiClient(cfg)
    if mode == "db":
        return MongoTraderClient(cfg)
    raise RuntimeError(f"Unknown backend_mode: {cfg.backend_mode!r}; expected 'db' or 'api'")
