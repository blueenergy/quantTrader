"""Execution Tracker for quantTrader.

This module handles proper execution tracking, replacing the immediate "filled" marking
with real execution status from the broker.
"""

import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from .api_client import TraderApiClient
from .broker_base import BrokerAdapter


class ExecutionStatus(Enum):
    """Execution status enum to match the backend system."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL_FILLED = "partial_filled"
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
    status: ExecutionStatus = ExecutionStatus.PENDING
    broker_order_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    retry_count: int = 0
    last_error: Optional[str] = None


class ExecutionTracker:
    """Tracks order execution lifecycle from submission to completion."""
    
    def __init__(self, api_client: TraderApiClient, broker: BrokerAdapter):
        self.api_client = api_client
        self.broker = broker
        self.logger = logging.getLogger(__name__)
        
        # In-memory tracking of pending executions
        self._pending_executions: Dict[str, ExecutionRecord] = {}
        self._broker_to_order_map: Dict[str, str] = {}  # broker_order_id -> order_id
        
        # Configuration
        self.max_retries = 3
        self.retry_delay = 5.0
    
    def submit_order(self, signal: Dict[str, Any]) -> bool:
        """Submit an order and track its execution lifecycle."""
        order_id = signal.get("order_id")
        if not order_id:
            self.logger.error("Signal missing order_id: %s", signal)
            return False
        
        # Create execution record
        execution = ExecutionRecord(
            order_id=order_id,
            symbol=signal.get("symbol", ""),
            action=signal.get("action", ""),
            size=signal.get("size", 0),
            target_price=signal.get("price"),
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
            
            # Store in tracking
            self._pending_executions[order_id] = execution
            self._broker_to_order_map[broker_order_id] = order_id
            
            # Update signal status to submitted
            self.api_client.update_signal_status(order_id, {
                "status": "submitted",
                "qmt_order_id": broker_order_id,
                "submitted_at": execution.updated_at,
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
    
    def poll_execution_status(self) -> None:
        """Poll for execution status updates from broker."""
        # For now, this is a simplified version
        # In a real implementation, this would query the broker for status updates
        # or use callbacks to receive real-time updates
        
        # Get current broker status (this would be implemented in the broker adapter)
        try:
            broker_executions = self.broker.get_execution_status()
            
            for broker_order_id, broker_status in broker_executions.items():
                order_id = self._broker_to_order_map.get(broker_order_id)
                if not order_id:
                    continue
                
                execution = self._pending_executions.get(order_id)
                if not execution:
                    continue
                
                # Update execution based on broker status
                new_status = self._map_broker_status(broker_status)
                execution.status = new_status
                execution.filled_size = broker_status.get('filled_size', 0)
                execution.filled_price = broker_status.get('avg_price')
                execution.updated_at = time.time()
                
                # Update backend
                self._update_execution_in_backend(execution, broker_status)
                
                # If order is completed, remove from pending
                if new_status in [ExecutionStatus.FILLED, ExecutionStatus.REJECTED, 
                                 ExecutionStatus.CANCELLED, ExecutionStatus.FAILED]:
                    self._complete_execution(order_id)
                    
        except Exception as e:
            self.logger.error("Error polling execution status: %s", e)
    
    def _map_broker_status(self, broker_status: Dict[str, Any]) -> ExecutionStatus:
        """Map broker status to internal execution status."""
        status = broker_status.get('status', '').lower()
        
        if status in ['filled', 'complete']:
            return ExecutionStatus.FILLED
        elif status in ['partial', 'partially_filled']:
            return ExecutionStatus.PARTIAL_FILLED
        elif status in ['rejected', 'failed']:
            return ExecutionStatus.REJECTED
        elif status in ['cancelled', 'canceled']:
            return ExecutionStatus.CANCELLED
        else:
            return ExecutionStatus.SUBMITTED  # Still processing
    
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
                "status": execution.status.value,
                "broker_order_id": execution.broker_order_id,
                "timestamp": execution.updated_at,
            }
            
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
                "updated_at": execution.updated_at,
            }
            
            if execution.status in [ExecutionStatus.FILLED, ExecutionStatus.REJECTED, 
                                   ExecutionStatus.CANCELLED, ExecutionStatus.FAILED]:
                signal_update["executed_at"] = execution.updated_at
            
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
    
    def __init__(self, api_client: TraderApiClient, broker: BrokerAdapter, 
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
                # Remove exchange suffix for standardization (e.g., "002050.SZ" -> "002050")
                base_symbol = symbol.split('.')[0] if '.' in symbol else symbol
                current_symbols.add(base_symbol)
                
                # Create position document with metadata
                position_doc = {
                    "symbol": base_symbol,
                    "qty": pos_data.get('qty', 0),
                    "can_use_volume": pos_data.get('can_use_volume', 0),
                    "frozen_volume": pos_data.get('frozen_volume', 0),
                    "avg_price": pos_data.get('avg_price', 0.0),
                    "market_value": pos_data.get('market_value', 0.0),
                    "on_road_volume": pos_data.get('on_road_volume', 0),
                    "timestamp": current_time,
                    "updated_at": time.time(),
                    "account_id": self.account_id,
                    "broker": self.broker_name,
                }
                
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
            # For now, return a basic summary - in a real implementation, 
            # we would query positions from backend to calculate metrics
            return {
                "total_positions": 0,  # Would be calculated from backend data
                "total_value": 0.0,
                "total_cost": 0.0,
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "positions": []
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