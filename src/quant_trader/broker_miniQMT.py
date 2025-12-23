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
            session_id = int(time.time())
            self.xt_trader = xttrader.XtQuantTrader(xt_path,session_id)

            self.xt_trader.start()
            
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
        from xtquant import xtconstant
        
        order_id = signal.get("order_id")
        symbol = signal.get("symbol")
        action = signal.get("action")
        size = signal.get("size")
        price = signal.get("price")
        
        if not all([symbol, action, size]):
            raise ValueError(f"Invalid signal: missing required fields. signal={signal}")
        
        # Normalize symbol: add exchange suffix if missing
        stock_code = symbol
        if "." not in stock_code:
            # Determine exchange by stock code pattern
            if stock_code.startswith(("6", "5")):
                stock_code = f"{stock_code}.SH"  # Shanghai: 60xxxx, 51xxxx
            elif stock_code.startswith(("0", "3", "2")):
                stock_code = f"{stock_code}.SZ"  # Shenzhen: 00xxxx, 30xxxx, 20xxxx
            else:
                log.warning("Unknown stock code pattern: %s, using as-is", stock_code)
        
        log.info("Normalized symbol: %s -> %s", symbol, stock_code)
        
        if action.upper() == "BUY":
            order_side = xtconstant.STOCK_BUY
        elif action.upper() == "SELL":
            order_side = xtconstant.STOCK_SELL
        else:
            raise ValueError(f"Invalid action: {action}. Must be BUY or SELL")

        # order_type: 价格类型（市价 / 限价）
        if price is None:
            # 市价单
            order_type = xtconstant.MARKET_PEER_PRICE_FIRST
            price_val = 0.0
        else:
            # 限价单
            order_type = xtconstant.FIX_PRICE
            price_val = float(price)

        log.info(
            "Placing miniQMT order: order_id=%s, symbol=%s, action=%s, size=%s, price=%s",
            order_id, stock_code, action, size, price
        )
        
        try:
            # Place order via miniQMT
            # order_stock(account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)
            qmt_order_id = self.xt_trader.order_stock(
                self.acc,
                stock_code,
                order_side,
                int(size),
                order_type,
                price_val
            )
            
            if qmt_order_id <= 0:
                raise RuntimeError(f"miniQMT returned invalid order_id: {qmt_order_id}")
            
            log.info("miniQMT order placed: qmt_order_id=%s for order_id=%s", qmt_order_id, order_id)
            return str(qmt_order_id)
            
        except Exception as e:
            log.exception("Failed to place order via miniQMT: %s", e)
            raise RuntimeError(f"miniQMT order failed: {e}") from e
    
    def query_positions(self) -> Dict[str, Dict[str, Any]]:
        """Query current positions from miniQMT.
        
        Returns:
            Dict of {symbol: position_data}
            
        Position data format:
            {
                "000858.SZ": {
                    "volume": 1000,              # Total shares
                    "can_use_volume": 800,       # Available to sell
                    "frozen_volume": 200,        # Frozen in orders
                    "open_price": 42.50,         # Average cost
                    "market_value": 43500.0,     # Current value
                    "last_price": 43.50,         # Current price
                    "on_road_volume": 0,         # In-transit shares
                    "yesterday_volume": 1000      # Previous day position
                }
            }
        """
        if not self.xt_trader or not self.acc:
            log.warning("miniQMT not connected, cannot query positions")
            return {}
        
        try:
            log.debug("Querying positions from miniQMT...")
            
            # Query stock positions
            # query_stock_positions(account) returns a list of position objects
            positions = self.xt_trader.query_stock_positions(self.acc)
            
            if not positions:
                log.debug("No positions found")
                return {}
            
            log.info("✓ Queried %d positions from miniQMT", len(positions))
            
            # Convert position data to standard format
            result = {}
            for pos in positions:
                symbol = pos.stock_code
                result[symbol] = {
                    "volume": pos.volume,
                    "can_use_volume": pos.can_use_volume,
                    "frozen_volume": pos.frozen_volume,
                    "open_price": pos.open_price,
                    "market_value": pos.market_value,
                    "last_price": pos.last_price,
                    "on_road_volume": getattr(pos, 'on_road_volume', 0),
                    "yesterday_volume": getattr(pos, 'yesterday_volume', 0)
                }
            
            return result
            
        except Exception as e:
            log.exception("Failed to query positions from miniQMT: %s", e)
            return {}
    
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
