from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .api_client import TraderApiClient
from .broker_base import BrokerAdapter
from .config import TraderConfig

log = logging.getLogger("quantTrader")


class TraderLoop:
    """Main trader loop.

    Pulls signals from backend, sends them to the broker, and reports
    executions back to backend via REST API.

    This minimal version uses a simple model: once an order is accepted
    by the broker, we immediately report it as fully filled (simulated
    execution). Later you can extend this to handle partial fills and
    real-time execution callbacks.
    """

    def __init__(self, cfg: TraderConfig, api: TraderApiClient, broker: BrokerAdapter) -> None:
        self.cfg = cfg
        self.api = api
        self.broker = broker
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        log.info("quantTrader started. API=%s", self.cfg.api_base_url)
        try:
            while not self._stop:
                try:
                    signals = self.api.get_pending_signals(limit=50, include_submitted=False)
                    if signals:
                        log.info("Fetched %d pending signals", len(signals))
                    for sig in signals:
                        self._handle_signal(sig)
                except Exception as e:  # noqa: BLE001
                    log.exception("Error in main loop: %s", e)

                time.sleep(self.cfg.poll_interval)
        finally:
            self.broker.close()
            log.info("quantTrader stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _handle_signal(self, sig: Dict[str, Any]) -> None:
        order_id = sig.get("order_id")
        if not order_id:
            log.warning("Skip signal without order_id: %s", sig)
            return

        try:
            # 1) send order to broker
            broker_order_id = self.broker.place_order(sig)

            # 2) mark as submitted
            self.api.update_signal_status(order_id, {
                "status": "submitted",
                "qmt_order_id": broker_order_id,
            })

            # 3) minimal version: treat as immediately filled
            filled_price = sig.get("price") or 100.0
            filled_size = sig.get("size") or 0

            execution = {
                "order_id": order_id,
                "symbol": sig.get("symbol"),
                "action": sig.get("action"),
                "size": sig.get("size"),
                "target_price": sig.get("price"),
                "filled_price": filled_price,
                "filled_size": filled_size,
                "commission": 0.0,
                "status": "filled",
                "broker": sig.get("broker", "simulated"),
                "mode": "live",
                "qmt_order_id": broker_order_id,
                "securities_account_id": sig.get("securities_account_id"),
                "account_id": sig.get("account_id"),
                "strategy": sig.get("strategy"),
                "strategy_name": sig.get("strategy_name", sig.get("strategy", "")),
            }
            self.api.create_execution(execution)
            log.info("Reported execution for order_id=%s", order_id)

        except Exception as e:  # noqa: BLE001
            log.error("Place order failed for %s: %s", order_id, e)
            # Minimal fallback: mark as retry_pending so backend/monitor can see it
            try:
                self.api.update_signal_status(order_id, {
                    "status": "retry_pending",
                    "last_error": str(e),
                })
            except Exception:  # noqa: BLE001
                log.exception("Failed to update signal status for %s", order_id)
