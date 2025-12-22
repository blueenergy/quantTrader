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

    @abstractmethod
    def close(self) -> None:
        """Clean up or disconnect from broker resources if needed."""
