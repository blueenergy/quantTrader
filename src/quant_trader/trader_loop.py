from __future__ import annotations

import json
import logging
import time
from datetime import datetime, time as dt_time, timezone
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

from .api_client import TraderApiClient
from .broker_base import BrokerAdapter
from .config import TraderConfig
from .execution_tracker import ExecutionTracker, EnhancedPositionManager
from .fee_model import TradeFeeModel
from .mongo_trader_client import MongoTraderClient

log = logging.getLogger("quantTrader")
CN_TZ = ZoneInfo("Asia/Shanghai")
CN_A_SESSIONS = ((dt_time(9, 25), dt_time(11, 30)), (dt_time(13, 0), dt_time(15, 0)))


def _parse_hhmm(value: str) -> Optional[dt_time]:
    try:
        hour, minute = str(value).strip().split(":", 1)
        return dt_time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


def _parse_session_windows(raw: Any) -> List[tuple[dt_time, dt_time]]:
    text = str(raw or "").strip()
    if not text:
        return []
    if text.upper() in {"CN_A", "CN_A_CONTINUOUS"}:
        return list(CN_A_SESSIONS)

    items: List[Any]
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            items = []
    else:
        items = [part.strip() for part in text.split(",") if part.strip()]

    windows: List[tuple[dt_time, dt_time]] = []
    for item in items:
        if isinstance(item, dict):
            start_raw = item.get("start")
            end_raw = item.get("end")
        else:
            if "-" not in str(item):
                continue
            start_raw, end_raw = str(item).split("-", 1)
        start = _parse_hhmm(str(start_raw))
        end = _parse_hhmm(str(end_raw))
        if start and end and start < end:
            windows.append((start, end))
    return windows


class TraderLoop:
    """Main trader loop.

    Pulls signals from backend (REST or MongoDB), sends them to the broker, and reports
    executions back via the configured trader client.
    
    Enhanced features:
    - Proper execution tracking (submitted → filled/partial/rejected)
    - Position synchronization from broker with metadata
    - Real-time portfolio monitoring
    - Strategy suggestions based on positions
    - Data foundation for AI analysis
    """

    def __init__(
        self,
        cfg: TraderConfig,
        api: Union[TraderApiClient, MongoTraderClient],
        broker: BrokerAdapter,
        enable_position_sync: bool = True,
        enable_execution_tracking: bool = True
    ) -> None:
        self.cfg = cfg
        self.api = api
        self.broker = broker
        self.fee_model = TradeFeeModel.from_config(cfg.fee_model)
        self._stop = False
        self._session_windows = _parse_session_windows(self.cfg.trading_sessions)
        
        # Execution tracker (replaces immediate 'filled' marking)
        self.execution_tracker: Optional[ExecutionTracker] = None
        if enable_execution_tracking:
            self.execution_tracker = ExecutionTracker(
                api_client=api,
                broker=broker,
                fee_model=self.fee_model,
                buy_order_timeout_seconds=self.cfg.buy_order_timeout_seconds,
                cancel_retry_grace_seconds=self.cfg.cancel_retry_grace_seconds,
                cancel_retry_interval_seconds=self.cfg.cancel_retry_interval_seconds,
            )
            log.info("Execution tracking ENABLED")
        self._last_heartbeat = 0.0
        
        # Enhanced position manager with metadata
        self.position_manager: Optional[EnhancedPositionManager] = None
        if enable_position_sync:
            self.position_manager = EnhancedPositionManager(
                api_client=api,
                broker=broker,
                sync_interval=60.0  # Sync every 60 seconds
            )
            log.info("Position synchronization ENABLED")

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        log.info("quantTrader started. backend=%s", self.cfg.backend_mode)
        if self.cfg.backend_mode.strip().lower() == "db":
            log.info(
                "Mongo backend: db=%s user_id=%s securities_account_id=%s",
                self.cfg.mongo_db,
                self.cfg.user_id,
                self.cfg.securities_account_id or "-",
            )
        else:
            log.info("API base URL: %s", self.cfg.api_base_url)
        log.info("Poll interval: %.1f seconds", self.cfg.poll_interval)
        log.info("Broker type: %s", type(self.broker).__name__)
        if self.position_manager:
            log.info("Position sync: ENABLED (interval=60s)")
        if self.execution_tracker:
            log.info("Execution tracking: ENABLED")

            # Resumption logic: Load existing submitted orders
            try:
                log.info("Checking for existing submitted orders to resume...")
                submitted_signals = self.api.get_submitted_signals()
                if submitted_signals:
                    log.info("Found %d submitted orders, attempting resume...", len(submitted_signals))
                    resumed_count = 0
                    for sig in submitted_signals:
                        if self.execution_tracker.attach_existing_order(sig):
                            resumed_count += 1
                    
                    if resumed_count > 0:
                        log.info("✓ Successfully resumed tracking for %d orders", resumed_count)
                        # Immediately poll to update status
                        self.execution_tracker.poll_execution_status()
                else:
                    log.debug("No existing orders found to resume")
            except Exception as e:
                log.error("Failed to resume orders: %s", e)
        
        try:
            while not self._stop:
                try:
                    # Sync positions periodically
                    account = None
                    if self.position_manager:
                        positions = self.position_manager.sync_positions()
                        account = self.position_manager.sync_account()
                        
                        if positions and account:
                            summary = self.position_manager.get_portfolio_summary()
                            # account is a dict, not an object
                            total_asset = account.get('total_asset', 0) if isinstance(account, dict) else account.total_asset
                            available_cash = account.get('available_cash', 0) if isinstance(account, dict) else account.available_cash
                            log.info(
                                "Portfolio: %d positions | Total=¥%.2f | Cash=¥%.2f | P&L=¥%.2f (%.2f%%)",
                                summary["total_positions"],
                                total_asset,
                                available_cash,
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
                    
                    sell_signals, buy_signals = self._split_ordered_signals(signals)
                    for sig in sell_signals:
                        self._handle_signal(sig, account=account)

                    # Let sell fills update before gated buys are considered.
                    if sell_signals and self.execution_tracker:
                        self.execution_tracker.poll_execution_status()
                    if sell_signals and self.position_manager:
                        account = self.position_manager.sync_account(force=True)

                    for sig in buy_signals:
                        self._handle_signal(sig, account=account)

                    # Poll execution status if enabled
                    if self.execution_tracker:
                        self.execution_tracker.poll_execution_status()

                    self._record_heartbeat()

                except Exception as e:  # noqa: BLE001
                    log.exception("Error in main loop: %s", e)

                time.sleep(self.cfg.poll_interval)
        finally:
            self.broker.close()
            log.info("quantTrader stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record_heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat < 30:
            return
        self._last_heartbeat = now
        try:
            self.api.record_heartbeat({
                "status": "running",
                "broker": type(self.broker).__name__,
                "api_base_url": self.cfg.api_base_url,
                "pending_execution_count": self.execution_tracker.get_pending_count() if self.execution_tracker else 0,
                "last_signal_poll_at": now,
                "account_id": getattr(self.position_manager, "account_id", None) if self.position_manager else None,
            })
        except Exception as exc:  # noqa: BLE001
            log.debug("Failed to record quantTrader heartbeat: %s", exc)

    def _split_ordered_signals(self, signals: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        ordered = sorted(signals, key=self._signal_sort_key)
        sell_signals = [sig for sig in ordered if self._signal_phase(sig) == "sell"]
        buy_signals = [sig for sig in ordered if self._signal_phase(sig) != "sell"]
        return sell_signals, buy_signals

    def _signal_sort_key(self, sig: Dict[str, Any]) -> tuple:
        phase_rank = 0 if self._signal_phase(sig) == "sell" else 1
        return (
            phase_rank,
            int(sig.get("execution_priority", 1000) or 1000),
            float(sig.get("timestamp", 0) or 0),
            str(sig.get("order_id") or ""),
        )

    def _signal_phase(self, sig: Dict[str, Any]) -> str:
        return str(sig.get("execution_phase") or sig.get("action") or "").lower()

    def _handle_signal(self, sig: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> None:
        order_id = sig.get("order_id")
        symbol = sig.get("symbol")
        action = sig.get("action")
        size = sig.get("size")
        
        log.info("Processing signal: order_id=%s, symbol=%s, action=%s, size=%s", 
                 order_id, symbol, action, size)
        
        if not order_id:
            log.warning("Skip signal without order_id: %s", sig)
            return
        if self.execution_tracker and self.execution_tracker.is_tracking(order_id):
            log.info("Skip already tracked signal: %s", order_id)
            return
        if not self._passes_execution_gates(sig, account):
            return

        # Use execution tracker for proper lifecycle management
        if self.execution_tracker:
            try:
                success = self.execution_tracker.submit_order(sig)
                if success:
                    log.info("Order submitted successfully: %s", order_id)
                else:
                    log.error("Failed to submit order: %s", order_id)
            except Exception as e:
                log.error("✗ Failed to submit signal %s: %s", order_id, e, exc_info=True)
                # Fallback: mark as retry_pending
                try:
                    self.api.update_signal_status(order_id, {
                        "status": "retry_pending",
                        "last_error": str(e),
                    })
                    log.info("Marked signal as retry_pending: %s", order_id)
                except Exception:  # noqa: BLE001
                    log.exception("Failed to update signal status for %s", order_id)
        else:
            # Fallback to old behavior if execution tracker not enabled
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
                filled_amount = float(filled_price or 0) * float(filled_size or 0)
                fee = self.fee_model.estimate(sig.get("action"), filled_amount)

                execution = {
                    "order_id": order_id,
                    "symbol": sig.get("symbol"),
                    "action": sig.get("action"),
                    "size": sig.get("size"),
                    "target_price": sig.get("price"),
                    "filled_price": filled_price,
                    "filled_size": filled_size,
                    **fee.to_dict(),
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

    def _passes_execution_gates(self, sig: Dict[str, Any], account: Optional[Dict[str, Any]]) -> bool:
        if not self._passes_schedule_gates(sig):
            return False
        action = str(sig.get("action") or "").lower()
        if action == "sell":
            return self._passes_sell_position_gate(sig)
        if action == "buy":
            return self._passes_buy_cash_gate(sig, account)
        return True

    def _passes_schedule_gates(self, sig: Dict[str, Any]) -> bool:
        order_id = sig.get("order_id")
        now_ts = time.time()

        if self.cfg.use_activate_after:
            activate_at = self._timestamp_or_none(sig.get("activate_after"))
            if activate_at is not None and now_ts < activate_at:
                log.info(
                    "Signal waits for activate_after: order_id=%s activate_after=%s",
                    order_id,
                    sig.get("activate_after"),
                )
                return False

        if not self._session_windows:
            return True

        local_now = datetime.fromtimestamp(now_ts, tz=timezone.utc).astimezone(CN_TZ)
        in_session = local_now.weekday() < 5 and any(start <= local_now.time() <= end for start, end in self._session_windows)
        if in_session:
            return True

        reason = "outside_trading_session"
        log.info("Signal waits for trading session: order_id=%s local_time=%s", order_id, local_now.isoformat())
        if self.cfg.reject_signals_outside_session:
            self._mark_signal_retry(sig, reason)
        return False

    def _passes_sell_position_gate(self, sig: Dict[str, Any]) -> bool:
        try:
            positions = self.broker.query_positions()
        except Exception as exc:  # noqa: BLE001
            log.warning("Unable to query positions before sell: %s", exc)
            self._mark_signal_retry(sig, "position_query_failed")
            return False
        if not positions:
            self._mark_signal_retry(sig, "position_unavailable")
            return False
        symbol = str(sig.get("symbol") or "")
        position = self._position_for_symbol(positions, symbol)
        available_qty = int((position or {}).get("can_use_volume") or (position or {}).get("volume") or 0)
        required_qty = int(sig.get("size", 0) or 0)
        if available_qty < required_qty:
            self._mark_signal_rejected(sig, f"insufficient_available_position available={available_qty} required={required_qty}")
            return False
        return True

    def _passes_buy_cash_gate(self, sig: Dict[str, Any], account: Optional[Dict[str, Any]]) -> bool:
        if not account:
            return True
        available_cash = float(account.get("available_cash") or account.get("cash") or 0)
        estimated_amount = self._estimated_signal_amount(sig)
        if estimated_amount <= 0:
            self._mark_signal_retry(sig, "missing_buy_price_for_cash_check")
            return False
        if estimated_amount > 0 and available_cash < estimated_amount:
            self._mark_signal_retry(sig, f"waiting_for_cash available={available_cash:.2f} required={estimated_amount:.2f}")
            return False
        return True

    @staticmethod
    def _position_for_symbol(positions: Dict[str, Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
        if symbol in positions:
            return positions[symbol]
        base = symbol.split(".", 1)[0]
        for candidate, position in positions.items():
            if str(candidate).split(".", 1)[0] == base:
                return position
        return None

    @staticmethod
    def _estimated_signal_amount(sig: Dict[str, Any]) -> float:
        try:
            size = int(sig.get("size", 0) or 0)
            price = float(sig.get("effective_limit_price") or sig.get("price") or sig.get("reference_price") or 0)
            return abs(size * price)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _timestamp_or_none(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            return ts / 1000.0 if ts > 1_000_000_000_000 else ts
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        try:
            normalized = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None

    def _mark_signal_retry(self, sig: Dict[str, Any], reason: str) -> None:
        order_id = sig.get("order_id")
        if not order_id:
            return
        log.info("Signal waits for retry: order_id=%s reason=%s", order_id, reason)
        self.api.update_signal_status(order_id, {
            "status": "retry_pending",
            "last_error": reason,
            "updated_at": time.time(),
        })

    def _mark_signal_rejected(self, sig: Dict[str, Any], reason: str) -> None:
        order_id = sig.get("order_id")
        if not order_id:
            return
        log.warning("Signal rejected before broker submission: order_id=%s reason=%s", order_id, reason)
        self.api.update_signal_status(order_id, {
            "status": "rejected",
            "last_error": reason,
            "updated_at": time.time(),
        })
