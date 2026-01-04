from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .broker_base import BrokerAdapter

log = logging.getLogger("quantTrader.simulated")


class SimulatedBroker(BrokerAdapter):
    """Minimal broker adapter that does *not* touch any real trading system.

    It only logs the orders and returns a fake broker_order_id. This is
    suitable for verifying the end-to-end REST integration safely.
    """

    def place_order(self, signal: Dict[str, Any]) -> str:
        order_id = signal.get("order_id")
        symbol = signal.get("symbol")
        action = signal.get("action")
        size = signal.get("size")
        price = signal.get("price")

        log.info(
            "SIMULATED place_order order_id=%s %s %s @ %s size=%s",
            order_id,
            action,
            symbol,
            price if price is not None else "MARKET",
            size,
        )

        # Sleep a bit to simulate network / broker latency
        time.sleep(0.1)

        # Fake broker order id
        broker_order_id = f"SIM-{int(time.time())}"
        return broker_order_id

    def get_execution_status(self) -> Dict[str, Dict[str, Any]]:
        """Get execution status for all tracked orders from simulated broker.
        
        In simulated mode, we could implement basic execution simulation.
        For now, returns empty dict.
        """
        return {}
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account metadata information for simulated broker.
        
        Returns:
            Dict with account metadata:
            - account_id: Broker-specific account ID
            - broker: Broker name/type
            - user_id: User ID (if applicable)
            - account_type: Account type
        """
        return {
            "account_id": "SIMULATED_ACCOUNT",
            "broker": "simulated",
            "account_type": "paper",
        }
    
    def close(self) -> None:
        log.info("SIMULATED broker closed")
