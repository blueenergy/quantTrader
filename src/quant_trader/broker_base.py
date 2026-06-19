from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BrokerQueryError(RuntimeError):
    """Raised when a broker snapshot query (orders/executions) is untrusted.

    Core invariant for the whole reconcile pipeline:

        Only a *successfully returned* order snapshot may be used to infer that
        an order no longer exists at the broker. An empty snapshot is valid
        information ("no live orders"); a failure is NOT.

    Implementations that DO support snapshot queries must raise this error (not
    return an empty dict) when the snapshot is unreliable, e.g. the broker is
    disconnected, the session/account is wrong, the API raised, or it returned
    ``None``. Collapsing those into ``{}`` would let callers mistake a disconnect
    for "broker has no orders" and wrongly reconcile ``submitted`` -> ``cancelled``.

    Consumers (e.g. ExecutionTracker.poll_execution_status) should catch this,
    skip the current poll cycle, and leave order state unchanged until a trusted
    snapshot is available again.
    """


class BrokerAdapter(ABC):
    """Abstract base class for broker integrations.

    quantTrader uses this abstraction so that different brokers
    (miniQMT, other APIs, paper trading, etc.) can be plugged in
    without changing the core trader loop.
    """

    @abstractmethod
    def place_order(self, signal: Dict[str, Any]) -> str:
        """Place an order at the broker and return broker_order_id.

        The *signal* is the raw document pulled from backend
        /api/trader/signals. Implementations can translate it into
        broker-specific order requests.
        """
    
    def query_positions(self) -> Dict[str, Dict[str, Any]]:
        """Query current positions from broker.
        
        Returns:
            Dict of {symbol: position_data}
            
        Position data should include:
            - volume: Total quantity
            - can_use_volume: Available quantity (not frozen)
            - frozen_volume: Frozen quantity in pending orders
            - open_price: Average cost per share
            - market_value: Current market value
            - last_price: Current market price
            
        Note: This is optional. Brokers that don't support position
        queries should return an empty dict.
        """
        return {}
    
    def query_account(self) -> Dict[str, Any]:
        """Query account information from broker.
        
        Returns:
            Dict with account data:
            - total_asset: Total account value (cash + positions)
            - cash: Available cash
            - frozen_cash: Cash frozen in pending orders
            - market_value: Total market value of positions
            - available_cash: Cash available for trading
            - buying_power: Maximum buying power
            - account_type: Account type (e.g., 'stock', 'margin')
            
        Note: This is optional. Brokers that don't support account
        queries should return an empty dict.
        """
        return {}
    
    def get_execution_status(self) -> Dict[str, Dict[str, Any]]:
        """Get execution status for all tracked orders.

        Three-state contract (see :class:`BrokerQueryError`):
            - success with orders -> non-empty dict {broker_order_id: data}
            - success with no orders -> empty dict (a valid "no live orders" snapshot)
            - untrusted snapshot (disconnect/session/API failure/None) -> raise
              :class:`BrokerQueryError`

        Execution status data should include:
            - status: Current status ('submitted', 'partial', 'filled', 'rejected', etc.)
            - filled_size: Number of shares filled
            - avg_price: Average execution price
            - commission: Commission paid
            - timestamp: Last update timestamp

        Note: This default is for brokers that do NOT support status queries; they
        return an empty dict. Brokers that DO support queries must raise
        :class:`BrokerQueryError` on failure instead of returning ``{}``, so an
        unreliable snapshot is never mistaken for "broker has no orders".
        """
        return {}

    def cancel_order(self, broker_order_id: str, *, client_order_id: Optional[str] = None) -> bool:
        """Cancel an outstanding broker order if supported.

        ``client_order_id`` is our signal ``order_id`` (e.g. live-plan-...); pass it
        so broker logs can be correlated with miniQMT ``broker_order_id``.

        Implementations should return True only when the cancel request was
        accepted by the broker. The final cancel/fill state still comes from
        get_execution_status().
        """
        return False
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account metadata information.
        
        Returns:
            Dict with account metadata:
            - account_id: Broker-specific account ID
            - broker: Broker name/type
            - user_id: User ID (if applicable)
            - account_type: Account type
            
        Note: This is optional. Brokers that don't support account
        info should return an empty dict.
        """
        return {}

    @abstractmethod
    def close(self) -> None:
        """Clean up or disconnect from broker resources if needed."""
