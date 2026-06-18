"""Execution Tracker for quantTrader.

This module handles proper execution tracking, replacing the immediate "filled" marking
with real execution status from the broker.
"""

import logging
import os
import time
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum

from .api_client import TraderApiClient
from .broker_base import BrokerAdapter
from .fee_model import TradeFeeModel
from .mongo_trader_client import MongoTraderClient

TraderBackend = Union[TraderApiClient, MongoTraderClient]

PRICE_TICK = Decimal("0.01")


class ExecutionStatus(Enum):
    """Execution status enum to match the backend system."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    CANCEL_REQUESTED = "cancel_requested"
    FILLED = "filled"
    PARTIAL_FILLED = "partial_filled"
    PARTIAL_CANCELLED = "partial_cancelled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"


@dataclass
class ExecutionRecord:
    """Execution record to track order lifecycle."""
    order_id: str
    symbol: str
    action: str
    size: int
    target_price: Optional[float] = None
    filled_price: Optional[float] = None
    filled_size: int = 0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    other_fee: float = 0.0
    total_fee: float = 0.0
    estimated_fee: bool = False
    status: ExecutionStatus = ExecutionStatus.PENDING
    broker_order_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    retry_count: int = 0
    last_error: Optional[str] = None
    securities_account_id: Optional[str] = None
    account_id: Optional[str] = None
    broker: Optional[str] = None
    mode: str = "live"
    strategy: Optional[str] = None
    execution_phase: Optional[str] = None
    execution_priority: int = 1000
    plan_item_rank: Optional[int] = None
    reference_price: Optional[float] = None
    max_slippage_bps: int = 100
    price_floor: Optional[float] = None
    price_ceiling: Optional[float] = None
    effective_limit_price: Optional[float] = None
    fee_model: Dict[str, Any] = field(default_factory=dict)
    valid_until: Optional[float] = None
    submitted_at: Optional[float] = None
    last_status_change_at: float = field(default_factory=time.time)
    cancel_requested_at: Optional[float] = None


class ExecutionTracker:
    """Tracks order execution lifecycle from submission to completion."""
    
    def __init__(self, api_client: TraderBackend, broker: BrokerAdapter, fee_model: Optional[TradeFeeModel] = None):
        self.api_client = api_client
        self.broker = broker
        self.fee_model = fee_model or TradeFeeModel()
        self.logger = logging.getLogger(__name__)
        
        # In-memory tracking of pending executions
        self._pending_executions: Dict[str, ExecutionRecord] = {}
        self._broker_to_order_map: Dict[str, str] = {}  # broker_order_id -> order_id
        
        # Configuration
        self.max_retries = 3
        self.retry_delay = 5.0
        self.order_timeout_seconds = 90.0
        self.buy_order_timeout_seconds = float(os.environ.get("QUANT_TRADER_BUY_ORDER_TIMEOUT_SECONDS", "3600"))
    
    def submit_order(self, signal: Dict[str, Any]) -> bool:
        """Submit an order and track its execution lifecycle."""
        order_id = signal.get("order_id")
        if not order_id:
            self.logger.error("Signal missing order_id: %s", signal)
            return False
        
        try:
            signal = self._prepare_signal_for_submission(signal)
        except Exception as e:
            self.logger.error("Signal %s failed execution guard: %s", order_id, e)
            self.api_client.update_signal_status(order_id, {
                "status": "retry_pending",
                "retry_count": int(signal.get("retry_count", 0) or 0) + 1,
                "last_error": str(e),
                "updated_at": time.time(),
            })
            return False

        # Create execution record
        execution = ExecutionRecord(
            order_id=order_id,
            symbol=signal.get("symbol", ""),
            action=signal.get("action", ""),
            size=int(signal.get("size", 0) or 0),
            target_price=signal.get("price"),
            securities_account_id=signal.get("securities_account_id"),
            account_id=signal.get("account_id"),
            broker=signal.get("broker"),
            mode=signal.get("mode", "live"),
            strategy=signal.get("strategy") or signal.get("strategy_id"),
            execution_phase=signal.get("execution_phase"),
            execution_priority=int(signal.get("execution_priority", 1000) or 1000),
            plan_item_rank=signal.get("plan_item_rank"),
            reference_price=signal.get("reference_price"),
            max_slippage_bps=int(signal.get("max_slippage_bps", 100) or 100),
            price_floor=signal.get("price_floor"),
            price_ceiling=signal.get("price_ceiling"),
            effective_limit_price=signal.get("effective_limit_price"),
            fee_model=signal.get("fee_model") or {},
            valid_until=self._timestamp_or_none(signal.get("valid_until")),
        )
        
        try:
            # Submit to broker
            broker_order_id = self.broker.place_order(signal)
            if not broker_order_id:
                self.logger.error("Failed to place order with broker for signal: %s", order_id)
                return False
            
            # Update execution record with broker order ID
            execution.broker_order_id = broker_order_id
            execution.status = ExecutionStatus.SUBMITTED
            execution.updated_at = time.time()
            execution.submitted_at = execution.updated_at
            
            # Store in tracking
            self._pending_executions[order_id] = execution
            self._broker_to_order_map[broker_order_id] = order_id
            
            # Update signal status to submitted
            self.api_client.update_signal_status(order_id, {
                "status": "submitted",
                "qmt_order_id": broker_order_id,
                "submitted_at": execution.updated_at,
                "effective_limit_price": execution.effective_limit_price,
                "execution_phase": execution.execution_phase,
            })
            
            self.logger.info("Order submitted: %s -> %s", order_id, broker_order_id)
            return True
            
        except Exception as e:
            self.logger.error("Error submitting order %s: %s", order_id, e)
            # Mark as retry pending
            execution.status = ExecutionStatus.RETRY_PENDING
            execution.retry_count += 1
            execution.last_error = str(e)
            execution.updated_at = time.time()
            
            self._pending_executions[order_id] = execution
            
            # Update signal status
            self.api_client.update_signal_status(order_id, {
                "status": "retry_pending",
                "retry_count": execution.retry_count,
                "last_error": execution.last_error,
                "updated_at": execution.updated_at,
            })
            
            
            return False
    
    def attach_existing_order(self, signal: Dict[str, Any]) -> bool:
        """Attach an existing submitted order to tracking.
        
        Used for resuming order tracking after restart.
        """
        order_id = signal.get("order_id")
        broker_order_id = signal.get("qmt_order_id") or signal.get("broker_order_id")
        
        if not order_id or not broker_order_id:
            self.logger.warning("Cannot attach order without order_id or qmt_order_id: %s", signal)
            return False
            
        if order_id in self._pending_executions:
            self.logger.info("Order %s already tracked, skipping attach", order_id)
            return True
            
        try:
            _base_ts = (
                self._timestamp_or_none(signal.get("submitted_at") or signal.get("timestamp"))
                or float(signal.get("updated_at") or time.time())
            )
            # Create execution record
            execution = ExecutionRecord(
                order_id=order_id,
                symbol=signal.get("symbol", ""),
                action=signal.get("action", ""),
                size=int(signal.get("size", 0) or 0),
                target_price=signal.get("price"),
                filled_price=signal.get("avg_price"),
                filled_size=int(signal.get("filled_qty", 0) or 0),
                broker_order_id=str(broker_order_id),
                status=self._status_from_signal(signal.get("status")),
                created_at=_base_ts,
                submitted_at=_base_ts,
                updated_at=float(signal.get("updated_at") or signal.get("submitted_at") or time.time()),
                securities_account_id=signal.get("securities_account_id"),
                account_id=signal.get("account_id"),
                broker=signal.get("broker"),
                mode=signal.get("mode", "live"),
                strategy=signal.get("strategy") or signal.get("strategy_id"),
                execution_phase=signal.get("execution_phase") or signal.get("action"),
                execution_priority=int(signal.get("execution_priority", 1000) or 1000),
                plan_item_rank=signal.get("plan_item_rank"),
                reference_price=signal.get("reference_price"),
                max_slippage_bps=int(signal.get("max_slippage_bps", 100) or 100),
                price_floor=signal.get("price_floor"),
                price_ceiling=signal.get("price_ceiling"),
                effective_limit_price=signal.get("effective_limit_price"),
                fee_model=signal.get("fee_model") or {},
                valid_until=self._timestamp_or_none(signal.get("valid_until")),
            )

            # Add to tracking
            self._pending_executions[order_id] = execution
            self._broker_to_order_map[str(broker_order_id)] = order_id
            
            self.logger.info("Resumed tracking for order: %s (broker_id=%s)", order_id, broker_order_id)
            return True
            
        except Exception as e:
            self.logger.error("Failed to attach order %s: %s", order_id, e)
            return False

    def poll_execution_status(self) -> None:
        """Poll for execution status updates from broker."""
        # For now, this is a simplified version
        # In a real implementation, this would query the broker for status updates
        # or use callbacks to receive real-time updates
        
        # Get current broker status (this would be implemented in the broker adapter)
        try:
            broker_executions = self.broker.get_execution_status()
            
            for broker_order_id, broker_status in broker_executions.items():
                broker_order_id = str(broker_order_id)
                order_id = self._broker_to_order_map.get(broker_order_id)
                if not order_id:
                    continue
                
                execution = self._pending_executions.get(order_id)
                if not execution:
                    continue
                
                # Update execution based on broker status
                new_status = self._map_broker_status(broker_status)
                if new_status != execution.status:
                    execution.last_status_change_at = time.time()
                execution.status = new_status
                execution.filled_size = broker_status.get('filled_size', 0)
                execution.filled_price = broker_status.get('avg_price')
                amount = float(execution.filled_size or 0) * float(execution.filled_price or 0.0)
                fee_model = TradeFeeModel.from_config(execution.fee_model) if execution.fee_model else self.fee_model
                fee = fee_model.extract_or_estimate(execution.action, amount, broker_status)
                execution.commission = fee.commission
                execution.stamp_tax = fee.stamp_tax
                execution.transfer_fee = fee.transfer_fee
                execution.other_fee = fee.other_fee
                execution.total_fee = fee.total_fee
                execution.estimated_fee = fee.estimated_fee
                execution.updated_at = time.time()
                
                # Update backend
                self._update_execution_in_backend(execution, broker_status)
                
                # If order is completed, remove from pending
                if new_status in [ExecutionStatus.FILLED, ExecutionStatus.REJECTED,
                                 ExecutionStatus.CANCELLED, ExecutionStatus.PARTIAL_CANCELLED, ExecutionStatus.FAILED]:
                    self._complete_execution(order_id)

            self._cancel_expired_pending_orders()
                    
        except Exception as e:
            self.logger.error("Error polling execution status: %s", e)

    def is_tracking(self, order_id: str) -> bool:
        """Return True when the order is already being tracked locally."""
        return str(order_id) in self._pending_executions

    def _prepare_signal_for_submission(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Apply execution guards before the broker sees the signal."""
        prepared = dict(signal)
        action = str(prepared.get("action") or "").lower()
        reference_price = self._float_or_none(prepared.get("reference_price") or prepared.get("price"))
        max_slippage_bps = int(prepared.get("max_slippage_bps", 100) or 100)

        if action == "sell":
            if reference_price is None or reference_price <= 0:
                raise ValueError("missing_reference_price")
            price_floor = self._float_or_none(prepared.get("price_floor"))
            computed_floor = self._protected_limit_price(reference_price, max_slippage_bps, action="sell")
            effective_limit_price = self._float_or_none(prepared.get("effective_limit_price"))
            if effective_limit_price is None:
                effective_limit_price = max(price_floor or 0, computed_floor)
            prepared["reference_price"] = reference_price
            prepared["price_floor"] = self._round_price_to_tick(price_floor if price_floor is not None else computed_floor, action="sell")
            prepared["effective_limit_price"] = self._round_price_to_tick(effective_limit_price, action="sell")
            prepared["price"] = prepared["effective_limit_price"]
            prepared["order_type"] = "limit"
        elif action == "buy":
            price_ceiling = self._float_or_none(prepared.get("price_ceiling") or prepared.get("effective_limit_price"))
            if price_ceiling is not None:
                prepared["effective_limit_price"] = self._round_price_to_tick(price_ceiling, action="buy")
                prepared["price"] = prepared["effective_limit_price"]
                prepared["order_type"] = "limit"
        return prepared

    def _cancel_expired_pending_orders(self) -> None:
        now = time.time()
        for order_id, execution in list(self._pending_executions.items()):
            action = str(execution.action).lower()
            if action not in {"sell", "buy"}:
                continue
            if execution.status not in {ExecutionStatus.SUBMITTED, ExecutionStatus.PARTIAL_FILLED}:
                continue
            if execution.cancel_requested_at:
                continue
            timeout = (
                self.buy_order_timeout_seconds if action == "buy" else self.order_timeout_seconds
            )
            expires_at = execution.valid_until or (execution.created_at + timeout)
            if now < expires_at:
                continue
            if not execution.broker_order_id:
                continue
            if not self.broker.cancel_order(execution.broker_order_id, client_order_id=order_id):
                self.logger.warning(
                    "Order expired but broker cancel was not accepted: client_order_id=%s "
                    "broker_order_id=%s action=%s (see miniQMT log line reason=... for "
                    "not_in_query vs still_active)",
                    order_id,
                    execution.broker_order_id,
                    action,
                )
                continue
            execution.cancel_requested_at = now
            execution.updated_at = now
            execution.status = ExecutionStatus.CANCEL_REQUESTED
            remaining_size = self._remaining_size(execution)
            chase_suggestion = self._build_chase_suggestion(execution, remaining_size)
            last_error = (
                "buy_order_expired_cancel_requested"
                if action == "buy"
                else "sell_order_expired_cancel_requested"
            )
            self.api_client.update_signal_status(order_id, {
                "status": ExecutionStatus.CANCEL_REQUESTED.value,
                "last_error": last_error,
                "cancel_requested_at": now,
                "filled_qty": execution.filled_size,
                "avg_price": execution.filled_price,
                "remaining_size": remaining_size,
                "chase_suggestion": chase_suggestion,
            })

    @staticmethod
    def _remaining_size(execution: ExecutionRecord) -> int:
        return max(0, int(execution.size or 0) - int(execution.filled_size or 0))

    def _build_chase_suggestion(self, execution: ExecutionRecord, remaining_size: Optional[int] = None) -> Dict[str, Any]:
        remaining = self._remaining_size(execution) if remaining_size is None else remaining_size
        next_slippage_bps = int(execution.max_slippage_bps or 100) + 30
        reference_price = execution.reference_price or execution.effective_limit_price or execution.target_price
        action = str(execution.action or "").lower()
        suggested_price = None
        if reference_price:
            suggested_price = self._protected_limit_price(
                reference_price, next_slippage_bps, action=action if action in {"buy", "sell"} else "sell"
            )
        reason = "buy_order_expired" if action == "buy" else "sell_order_expired"
        return {
            "mode": "manual_review",
            "reason": reason,
            "action": action,
            "remaining_size": remaining,
            "reference_price": reference_price,
            "current_limit_price": execution.effective_limit_price,
            "suggested_limit_price": suggested_price,
            "suggested_max_slippage_bps": next_slippage_bps,
            "auto_resubmit": False,
        }

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _round_price_to_tick(price: float, *, action: str) -> float:
        decimal_price = Decimal(str(price))
        rounding = ROUND_FLOOR if action == "sell" else ROUND_CEILING
        return float(decimal_price.quantize(PRICE_TICK, rounding=rounding))

    @staticmethod
    def _protected_limit_price(reference_price: float, max_slippage_bps: int, *, action: str) -> float:
        reference = Decimal(str(reference_price))
        slippage = Decimal(int(max_slippage_bps)) / Decimal("10000")
        multiplier = Decimal("1") - slippage if action == "sell" else Decimal("1") + slippage
        rounding = ROUND_FLOOR if action == "sell" else ROUND_CEILING
        return float((reference * multiplier).quantize(PRICE_TICK, rounding=rounding))

    @staticmethod
    def _timestamp_or_none(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                from datetime import datetime

                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None
    
    def _map_broker_status(self, broker_status: Dict[str, Any]) -> ExecutionStatus:
        """Map broker status to internal execution status."""
        status = broker_status.get('status', '').lower()
        
        if status in ['filled', 'complete', 'filled_all', 'all_traded']:
            return ExecutionStatus.FILLED
        elif status in ['partial', 'partially_filled', 'partial_filled', 'part_traded']:
            return ExecutionStatus.PARTIAL_FILLED
        elif status in ['rejected', 'failed', 'error']:
            return ExecutionStatus.REJECTED
        elif status in ['partial_cancelled']:
            return ExecutionStatus.PARTIAL_CANCELLED
        elif status in ['cancelled', 'canceled']:
            return ExecutionStatus.CANCELLED
        elif status in ['submitted', 'accepted', 'reported', 'pending']:
            return ExecutionStatus.SUBMITTED
        else:
            return ExecutionStatus.SUBMITTED  # Still processing

    @staticmethod
    def _extract_last_market_price(broker_status: Dict[str, Any]) -> Optional[float]:
        for key in ("last_price", "market_price", "current_price", "price", "close"):
            v = broker_status.get(key)
            if v is None:
                continue
            try:
                f = float(v)
                if f > 0:
                    return f
            except (TypeError, ValueError):
                continue
        return None

    def _status_from_signal(self, status: Any) -> ExecutionStatus:
        text = str(status or "").lower()
        if text == "partial_filled":
            return ExecutionStatus.PARTIAL_FILLED
        if text == "cancel_requested":
            return ExecutionStatus.CANCEL_REQUESTED
        return ExecutionStatus.SUBMITTED
    
    def _update_execution_in_backend(self, execution: ExecutionRecord, broker_status: Dict[str, Any]) -> None:
        """Update execution in backend system."""
        try:
            # Create execution record for backend
            execution_record = {
                "order_id": execution.order_id,
                "symbol": execution.symbol,
                "action": execution.action,
                "size": execution.size,
                "target_price": execution.target_price,
                "filled_price": execution.filled_price,
                "filled_size": execution.filled_size,
                "commission": execution.commission,
                "stamp_tax": execution.stamp_tax,
                "transfer_fee": execution.transfer_fee,
                "other_fee": execution.other_fee,
                "total_fee": execution.total_fee,
                "estimated_fee": execution.estimated_fee,
                "status": execution.status.value,
                "broker_order_id": execution.broker_order_id,
                "qmt_order_id": execution.broker_order_id,
                "timestamp": execution.updated_at,
                "securities_account_id": execution.securities_account_id,
                "account_id": execution.account_id,
                "broker": execution.broker,
                "mode": execution.mode,
                "strategy": execution.strategy,
                "execution_phase": execution.execution_phase,
                "execution_priority": execution.execution_priority,
                "plan_item_rank": execution.plan_item_rank,
                "reference_price": execution.reference_price,
                "max_slippage_bps": execution.max_slippage_bps,
                "price_floor": execution.price_floor,
                "price_ceiling": execution.price_ceiling,
                "effective_limit_price": execution.effective_limit_price,
                "fee_model": execution.fee_model,
                "remaining_size": self._remaining_size(execution),
            }
            if execution.status in {ExecutionStatus.CANCEL_REQUESTED, ExecutionStatus.PARTIAL_CANCELLED}:
                execution_record["chase_suggestion"] = self._build_chase_suggestion(execution)
            
            # Add any additional broker-specific fields
            for key, value in broker_status.items():
                if key not in execution_record:
                    execution_record[key] = value
            
            # Create execution in backend
            self.api_client.create_execution(execution_record)
            
            # Update signal status
            signal_update = {
                "status": execution.status.value,
                "filled_qty": execution.filled_size,
                "avg_price": execution.filled_price,
                "effective_limit_price": execution.effective_limit_price,
                "remaining_size": self._remaining_size(execution),
                "updated_at": execution.updated_at,
            }
            if execution.status in {ExecutionStatus.CANCEL_REQUESTED, ExecutionStatus.PARTIAL_CANCELLED}:
                signal_update["chase_suggestion"] = self._build_chase_suggestion(execution)
            
            if execution.status in [ExecutionStatus.FILLED, ExecutionStatus.REJECTED,
                                   ExecutionStatus.CANCELLED, ExecutionStatus.PARTIAL_CANCELLED, ExecutionStatus.FAILED]:
                signal_update["executed_at"] = execution.updated_at

            if execution.status in {ExecutionStatus.SUBMITTED, ExecutionStatus.PARTIAL_FILLED}:
                now_ts = float(execution.updated_at)
                base_ts = float(execution.submitted_at or execution.created_at)
                signal_update["submitted_age_seconds"] = max(0.0, now_ts - base_ts)
                signal_update["broker_status"] = str(broker_status.get("status") or "")
                signal_update["broker_status_msg"] = str(
                    broker_status.get("message")
                    or broker_status.get("status_msg")
                    or broker_status.get("error_msg")
                    or ""
                )
                signal_update["last_status_checked_at"] = now_ts
                lm = self._extract_last_market_price(broker_status)
                if lm is not None:
                    signal_update["last_market_price"] = lm

            self.api_client.update_signal_status(execution.order_id, signal_update)
            
        except Exception as e:
            self.logger.error("Error updating execution in backend for %s: %s", 
                            execution.order_id, e)
    
    def _complete_execution(self, order_id: str) -> None:
        """Remove completed execution from tracking."""
        execution = self._pending_executions.pop(order_id, None)
        if execution and execution.broker_order_id:
            self._broker_to_order_map.pop(execution.broker_order_id, None)
    
    def get_pending_count(self) -> int:
        """Get count of pending executions."""
        return len(self._pending_executions)
    
    def get_execution_status(self, order_id: str) -> Optional[ExecutionStatus]:
        """Get status of a specific execution."""
        execution = self._pending_executions.get(order_id)
        return execution.status if execution else None


class EnhancedPositionManager:
    """Enhanced position manager with account metadata and position cleanup."""
    
    def __init__(self, api_client: TraderBackend, broker: BrokerAdapter,
                 sync_interval: float = 60.0):
        self.api_client = api_client
        self.broker = broker
        self.sync_interval = sync_interval
        self.logger = logging.getLogger(__name__)
        
        # Track last sync time
        self._last_sync = 0
        self._last_account_sync = 0
        
        # Account info cache
        self._account_info_cache = None
        
        # Get account metadata from broker
        try:
            self.account_info = self.broker.get_account_info()
            self.account_id = self.account_info.get("account_id")
            self.broker_name = self.account_info.get("broker", "unknown")
        except:
            self.account_info = {}
            self.account_id = None
            self.broker_name = "unknown"
    
    def sync_account(self, force: bool = False):
        """Sync account information from broker.
        
        Args:
            force: Force sync even if within sync interval
            
        Returns:
            Account data from broker or cached data
        """
        current_time = time.time()
        
        # Rate limiting
        if not force and (current_time - self._last_account_sync < self.sync_interval):
            self.logger.debug("Skipping account sync (within interval)")
            return self._account_info_cache
        
        if not self.broker:
            self.logger.warning("No broker configured, cannot sync account")
            return self._account_info_cache
        
        try:
            # Query account from broker
            account_data = self.broker.query_account()
            
            if not account_data:
                self.logger.warning("No account data returned from broker")
                self._last_account_sync = current_time
                return self._account_info_cache
            
            # Update cache
            self._account_info_cache = account_data
            self._last_account_sync = current_time
            
            # Push to backend
            try:
                response = self.api_client.sync_account(account_data)
                if response.get("success"):
                    self.logger.debug("Account info synced to backend")
                else:
                    self.logger.warning("Backend returned non-success for account sync")
            except Exception as e:
                self.logger.warning("Failed to push account to backend: %s", e)
            
            self.logger.info(
                "✓ Account synced: Total=¥%.2f, Cash=¥%.2f, Available=¥%.2f, Market=¥%.2f",
                account_data.get('total_asset', 0),
                account_data.get('cash', 0),
                account_data.get('available_cash', 0),
                account_data.get('market_value', 0)
            )
            
            return account_data
            
        except Exception as e:
            self.logger.exception("Failed to sync account: %s", e)
            return self._account_info_cache    
    def sync_positions(self) -> bool:
        """Sync positions from broker to backend with metadata."""
        current_time = time.time()
        if current_time - self._last_sync < self.sync_interval:
            return False  # Skip sync if too soon
        
        try:
            self._last_sync = current_time
            
            # Get positions from broker
            broker_positions = self.broker.query_positions()
            if not broker_positions:
                self.logger.debug("No positions to sync")
                # Still need to cleanup stale positions (remove all since no positions held)
                self.api_client.cleanup_stale_positions([], account_id=self.account_id)
                return True
            
            # Get current symbols to identify stale positions
            current_symbols = set()
            position_updates = []
            
            for symbol, pos_data in broker_positions.items():
                # Preserve exchange suffix for consistency with order placement (e.g., "002050.SZ")
                current_symbols.add(symbol)
                
                # Create position document with metadata
                position_doc = {
                    "symbol": symbol,
                    "qty": pos_data.get('volume', 0),  # Map 'volume' from broker to 'qty' for storage
                    "can_use_volume": pos_data.get('can_use_volume', 0),
                    "frozen_volume": pos_data.get('frozen_volume', 0),
                    "avg_price": pos_data.get('open_price', 0.0),  # Map 'open_price' from broker to 'avg_price' for storage
                    "last_price": pos_data.get('last_price', 0.0),  # Add current market price
                    "market_value": pos_data.get('market_value', 0.0),
                    "on_road_volume": pos_data.get('on_road_volume', 0),
                    "timestamp": current_time,
                    "updated_at": time.time(),
                    "account_id": self.account_id,
                    "broker": self.broker_name,
                }
                
                # Calculate unrealized P&L
                avg_price = pos_data.get('open_price', 0.0)
                quantity = pos_data.get('volume', 0)
                market_value = pos_data.get('market_value', 0.0)
                last_price = pos_data.get('last_price', avg_price)
                
                cost_basis = avg_price * quantity
                unrealized_pnl = market_value - cost_basis if market_value != 0 else (last_price * quantity) - cost_basis
                unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                
                # Add P&L fields to position document
                position_doc["unrealized_pnl"] = unrealized_pnl
                position_doc["unrealized_pnl_pct"] = unrealized_pnl_pct
                
                position_updates.append(position_doc)
            
            # Sync positions to backend
            if position_updates:
                self.api_client.sync_positions(position_updates)
            
            # Cleanup stale positions (not held in broker anymore)
            # Always call cleanup even if no current symbols to remove all stale positions
            self.api_client.cleanup_stale_positions(list(current_symbols), 
                                                 account_id=self.account_id)
            
            self.logger.info("Synced %d positions to backend", len(position_updates))
            return True
            
        except Exception as e:
            self.logger.error("Error syncing positions: %s", e)
            return False
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary by querying current positions from backend.
        
        Since EnhancedPositionManager doesn't maintain local cache like the original PositionManager,
        we query the backend for current position data to calculate summary.
        
        Returns:
            Dict with portfolio metrics
        """
        try:
            # Calculate from current positions (since we just synced)
            positions = self.broker.query_positions()
            
            total_value = 0.0
            total_cost = 0.0
            total_pnl = 0.0
            
            for symbol, pos_data in positions.items():
                quantity = pos_data.get('volume', 0)
                avg_price = pos_data.get('open_price', 0.0)
                market_value = pos_data.get('market_value', 0.0)
                last_price = pos_data.get('last_price', avg_price)
                
                cost_basis = avg_price * quantity
                # Use market_value if available, otherwise calculate from last_price
                current_value = market_value if market_value != 0 else last_price * quantity
                pnl = current_value - cost_basis
                
                total_value += current_value
                total_cost += cost_basis
                total_pnl += pnl
            
            total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
            
            return {
                "total_positions": len(positions),
                "total_value": total_value,
                "total_cost": total_cost,
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "positions": []  # Could be expanded to include position details
            }
        except Exception as e:
            self.logger.error("Error getting portfolio summary: %s", e)
            return {
                "total_positions": 0,
                "total_value": 0.0,
                "total_cost": 0.0,
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "positions": []
            }