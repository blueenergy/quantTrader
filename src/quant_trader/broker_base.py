from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


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

    @abstractmethod
    def close(self) -> None:
        """Clean up or disconnect from broker resources if needed."""
