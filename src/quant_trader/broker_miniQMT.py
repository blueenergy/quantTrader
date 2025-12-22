"""
miniQMT Broker Adapter for quantTrader.

Integrates with XtQuant (miniQMT) Python API for real order execution on Windows.
"""

import logging
import time
from typing import Any, Dict, Optional

from quant_trader.broker_base import BrokerAdapter

log = logging.getLogger(__name__)


class MiniQMTBroker(BrokerAdapter):
    """
    Real broker adapter for miniQMT (XtQuant).
    
    Requirements:
    - Windows OS
    - miniQMT installed (国金QMT交易端模拟 or similar)
    - xtquant Python package installed
    
    Configuration (in config.json):
    {
      "broker": "miniQMT",
      "miniQMT": {
        "xt_path": "C:\\国金QMT交易端模拟\\userdata_mini",
        "account_id": "62666676"
      }
    }
    """
    
    def __init__(self, xt_path: str, account_id: str) -> None:
        """
        Initialize miniQMT broker.
        
        Args:
            xt_path: Path to miniQMT userdata_mini directory
            account_id: Trading account ID
        """
        self.xt_path = xt_path
        self.account_id = account_id
        self.xt_trader = None
        self.acc = None
        
        log.info("Initializing miniQMT broker: xt_path=%s, account_id=%s", xt_path, account_id)
        
        try:
            # Import xtquant modules (only available on Windows with miniQMT)
            from xtquant import xttrader
            from xtquant.xttype import StockAccount
            
            # Initialize trader
            self.xt_trader = xttrader.XtQuantTrader(xt_path, session_id=int(time.time()))
            
            # Connect
            log.info("Connecting to miniQMT...")
            connect_result = self.xt_trader.connect()
            if connect_result != 0:
                raise RuntimeError(f"Failed to connect to miniQMT: error_code={connect_result}")
            
            log.info("miniQMT connected successfully")
            
            # Create account object
            self.acc = StockAccount(account_id)
            
            # Subscribe to account
            log.info("Subscribing to account: %s", account_id)
            subscribe_result = self.xt_trader.subscribe(self.acc)
            if subscribe_result != 0:
                raise RuntimeError(f"Failed to subscribe account: error_code={subscribe_result}")
            
            log.info("miniQMT broker initialized successfully")
            
        except ImportError as e:
            log.error("Failed to import xtquant: %s", e)
            log.error("Make sure you're running on Windows with miniQMT installed")
            log.error("Install xtquant: pip install xtquant")
            raise RuntimeError("xtquant not available - miniQMT broker requires Windows + miniQMT") from e
        except Exception as e:
            log.exception("Failed to initialize miniQMT broker: %s", e)
            raise
    
    def place_order(self, signal: Dict[str, Any]) -> str:
        """
        Place an order via miniQMT.
        
        Args:
            signal: Trade signal dict with:
                - symbol: Stock code (e.g., "000858.SZ")
                - action: "BUY" or "SELL"
                - size: Quantity
                - price: Limit price (None for market order)
                - order_id: Backend order ID
        
        Returns:
            miniQMT order ID (qmt_order_id)
        
        Raises:
            RuntimeError: If order placement fails
        """
        from xtquant.xttype import XtOrderType
        
        order_id = signal.get("order_id")
        symbol = signal.get("symbol")
        action = signal.get("action")
        size = signal.get("size")
        price = signal.get("price")
        
        if not all([symbol, action, size]):
            raise ValueError(f"Invalid signal: missing required fields. signal={signal}")
        
        # Map action to miniQMT side
        # 23 = Buy, 24 = Sell (XtQuantTrader constants)
        stock_code = symbol
        order_type = XtOrderType.LIMIT_ORDER if price else XtOrderType.MARKET_ORDER
        
        if action.upper() == "BUY":
            order_side = 23  # Buy
        elif action.upper() == "SELL":
            order_side = 24  # Sell
        else:
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")
        
        log.info(
            "Placing miniQMT order: order_id=%s, symbol=%s, action=%s, size=%s, price=%s",
            order_id, stock_code, action, size, price
        )
        
        try:
            # Place order via miniQMT
            # order_stock(account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)
            qmt_order_id = self.xt_trader.order_stock(
                account=self.acc,
                stock_code=stock_code,
                order_type=order_type,
                order_volume=int(size),
                price_type=1 if price else 0,  # 1=limit, 0=market
                price=float(price) if price else 0.0,
                strategy_name="quantTrader",
                order_remark=f"order_id:{order_id}"
            )
            
            if qmt_order_id <= 0:
                raise RuntimeError(f"miniQMT returned invalid order_id: {qmt_order_id}")
            
            log.info("miniQMT order placed: qmt_order_id=%s for order_id=%s", qmt_order_id, order_id)
            return str(qmt_order_id)
            
        except Exception as e:
            log.exception("Failed to place order via miniQMT: %s", e)
            raise RuntimeError(f"miniQMT order failed: {e}") from e
    
    def close(self) -> None:
        """
        Disconnect from miniQMT and cleanup resources.
        """
        log.info("Closing miniQMT broker")
        
        if self.xt_trader and self.acc:
            try:
                # Unsubscribe from account
                log.info("Unsubscribing from account: %s", self.account_id)
                self.xt_trader.unsubscribe(self.acc)
            except Exception as e:
                log.warning("Failed to unsubscribe account: %s", e)
        
        log.info("miniQMT broker closed")
