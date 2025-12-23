from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from .api_client import TraderApiClient
from .broker_base import BrokerAdapter
from .config import TraderConfig
from .position_manager import PositionManager

log = logging.getLogger("quantTrader")


class TraderLoop:
    """Main trader loop.

    Pulls signals from backend, sends them to the broker, and reports
    executions back to backend via REST API.
    
    Enhanced features:
    - Position synchronization from broker
    - Real-time portfolio monitoring
    - Strategy suggestions based on positions
    - Data foundation for AI analysis
    """

    def __init__(
        self,
        cfg: TraderConfig,
        api: TraderApiClient,
        broker: BrokerAdapter,
        enable_position_sync: bool = True
    ) -> None:
        self.cfg = cfg
        self.api = api
        self.broker = broker
        self._stop = False
        
        # Position manager (optional)
        self.position_manager: Optional[PositionManager] = None
        if enable_position_sync:
            self.position_manager = PositionManager(
                api_client=api,
                broker=broker,
                sync_interval=60.0  # Sync every 60 seconds
            )
            log.info("Position synchronization ENABLED")

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        log.info("quantTrader started. API=%s", self.cfg.api_base_url)
        log.info("Poll interval: %.1f seconds", self.cfg.poll_interval)
        log.info("Broker type: %s", type(self.broker).__name__)
        if self.position_manager:
            log.info("Position sync: ENABLED (interval=60s)")
        
        try:
            while not self._stop:
                try:
                    # Sync positions periodically
                    if self.position_manager:
                        positions = self.position_manager.sync_positions()
                        if positions:
                            summary = self.position_manager.get_portfolio_summary()
                            log.info(
                                "Portfolio: %d positions, Value=¥%.2f, P&L=¥%.2f (%.2f%%)",
                                summary["total_positions"],
                                summary["total_value"],
                                summary["total_pnl"],
                                summary["total_pnl_pct"]
                            )
                    
                    # Poll for trading signals
                    log.debug("Polling for signals...")
                    signals = self.api.get_pending_signals(limit=50, include_submitted=False)
                    
                    if signals:
                        log.info("Fetched %d pending signals", len(signals))
                    else:
                        log.debug("No pending signals found")
                    
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
        symbol = sig.get("symbol")
        action = sig.get("action")
        size = sig.get("size")
        
        log.info("Processing signal: order_id=%s, symbol=%s, action=%s, size=%s", 
                 order_id, symbol, action, size)
        
        if not order_id:
            log.warning("Skip signal without order_id: %s", sig)
            return

        try:
            # 1) send order to broker
            log.debug("Placing order to broker: %s", order_id)
            broker_order_id = self.broker.place_order(sig)
            log.info("Order placed successfully: order_id=%s, broker_order_id=%s", 
                     order_id, broker_order_id)

            # 2) mark as submitted
            log.debug("Updating signal status to 'submitted': %s", order_id)
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
            
            log.debug("Reporting execution: %s", order_id)
            self.api.create_execution(execution)
            log.info("✓ Execution reported successfully: order_id=%s, symbol=%s, action=%s", 
                     order_id, symbol, action)

        except Exception as e:  # noqa: BLE001
            log.error("✗ Failed to process signal %s: %s", order_id, e, exc_info=True)
            # Minimal fallback: mark as retry_pending so backend/monitor can see it
            try:
                self.api.update_signal_status(order_id, {
                    "status": "retry_pending",
                    "last_error": str(e),
                })
                log.info("Marked signal as retry_pending: %s", order_id)
            except Exception:  # noqa: BLE001
                log.exception("Failed to update signal status for %s", order_id)
