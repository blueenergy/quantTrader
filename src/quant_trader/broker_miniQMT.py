"""
miniQMT Broker Adapter for quantTrader.

Integrates with XtQuant (miniQMT) Python API for real order execution on Windows.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

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
        price = signal.get("effective_limit_price")
        if price is None:
            price = signal.get("price")
        order_type_value = str(signal.get("order_type") or "").lower()
        
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
        if price is None or order_type_value == "market":
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

    _TERMINAL_QUERY_STATUSES = frozenset(
        {"cancelled", "filled", "partial_cancelled", "rejected"}
    )

    def _query_order_row_with_diag(
        self, broker_order_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Return (query_orders row, diagnostic) for cancel / troubleshooting logs."""
        diagnostic: Dict[str, Any] = {
            "lookup_raw": str(broker_order_id),
            "lookup_key": None,
            "query_returned_orders": None,
            "matched": False,
            "parse_error": None,
        }
        try:
            oid = int(str(broker_order_id).strip())
        except (TypeError, ValueError) as exc:
            diagnostic["parse_error"] = str(exc)
            return None, diagnostic

        key = str(oid)
        diagnostic["lookup_key"] = key
        orders = self.query_orders()
        if not orders:
            diagnostic["query_returned_orders"] = 0
            return None, diagnostic

        diagnostic["query_returned_orders"] = len(orders)
        row = orders.get(key)
        diagnostic["matched"] = row is not None
        return row, diagnostic

    def _order_row_from_query(self, broker_order_id: str) -> Optional[Dict[str, Any]]:
        """Return query_orders() row for this broker order id, if any."""
        row, _ = self._query_order_row_with_diag(broker_order_id)
        return row

    def cancel_order(self, broker_order_id: str, *, client_order_id: Optional[str] = None) -> bool:
        """Cancel an outstanding miniQMT order.

        xtquant often returns ``0`` on success. ``-1`` is a generic failure but
        commonly occurs when the order is already finished (filled/cancelled)
        or outside cancelable session rules. In that case we re-query
        ``query_stock_orders`` and treat already-terminal states as success so
        the execution tracker can advance ``cancel_requested`` / sync Mongo.

        If the cancel API fails but the same query returns **other** today's
        orders while **this** ``broker_order_id`` is missing, we treat cancel as
        **success** (idempotent): QMT no longer lists this entrust id, so there
        is nothing to cancel at the broker. When the query list is empty we stay
        conservative and return failure (ambiguous vs disconnected).

        ``client_order_id`` is our signal ``order_id`` (e.g. live-plan-...); it is
        included in logs next to ``broker_order_id`` (QMT entrust id).
        """
        if not self.xt_trader or not self.acc:
            log.warning(
                "miniQMT not connected, cannot cancel order client_order_id=%s broker_order_id=%s",
                client_order_id or "-",
                broker_order_id,
            )
            return False
        try:
            order_id = int(broker_order_id)
            cancel_fn = getattr(self.xt_trader, "cancel_order_stock", None) or getattr(self.xt_trader, "cancel_order", None)
            if not cancel_fn:
                log.warning("miniQMT cancel API is not available")
                return False
            result = cancel_fn(self.acc, order_id)
            log.info(
                "miniQMT cancel requested: client_order_id=%s broker_order_id=%s result=%s",
                client_order_id or "-",
                broker_order_id,
                result,
            )
            if result == 0 or result is True:
                return True

            row, diag = self._query_order_row_with_diag(broker_order_id)
            if row and row.get("status") in self._TERMINAL_QUERY_STATUSES:
                log.info(
                    "miniQMT cancel returned %r but order already terminal in query: "
                    "client_order_id=%s broker_order_id=%s status=%s msg=%s "
                    "query_returned_orders=%s",
                    result,
                    client_order_id or "-",
                    broker_order_id,
                    row.get("status"),
                    row.get("status_msg"),
                    diag.get("query_returned_orders"),
                )
                return True

            if diag.get("parse_error"):
                log.warning(
                    "miniQMT cancel failed: client_order_id=%s broker_order_id=%s result=%s "
                    "reason=invalid_broker_order_id parse_error=%s",
                    client_order_id or "-",
                    broker_order_id,
                    result,
                    diag.get("parse_error"),
                )
                return False

            if not row:
                n_orders = int(diag.get("query_returned_orders") or 0)
                log.warning(
                    "miniQMT cancel returned %s: client_order_id=%s broker_order_id=%s "
                    "reason=order_not_in_query_stock_orders "
                    "query_returned_orders=%s lookup_key=%s "
                    "(QMT may have dropped this id from today's list, wrong account/session, "
                    "or query lag; confirm in QMT UI)",
                    result,
                    client_order_id or "-",
                    broker_order_id,
                    n_orders,
                    diag.get("lookup_key"),
                )
                if n_orders > 0:
                    log.info(
                        "miniQMT cancel treating as success (idempotent): entrust id absent "
                        "from non-empty query_stock_orders client_order_id=%s broker_order_id=%s",
                        client_order_id or "-",
                        broker_order_id,
                    )
                    return True
                return False

            log.warning(
                "miniQMT cancel failed: client_order_id=%s broker_order_id=%s result=%s "
                "reason=order_still_active_in_query mapped_status=%s qmt_status=%s msg=%s "
                "query_returned_orders=%s",
                client_order_id or "-",
                broker_order_id,
                result,
                row.get("status"),
                row.get("qmt_status"),
                row.get("status_msg"),
                diag.get("query_returned_orders"),
            )
            return False
        except Exception as e:
            log.exception(
                "Failed to cancel miniQMT order client_order_id=%s broker_order_id=%s: %s",
                client_order_id or "-",
                broker_order_id,
                e,
            )
            return False
    
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
    
    def query_account(self) -> Dict[str, Any]:
        """Query account information from miniQMT.
        
        Returns:
            Dict with account data:
            {
                "total_asset": 500000.0,      # Total account value
                "cash": 120000.0,              # Available cash
                "frozen_cash": 5000.0,         # Frozen in orders
                "market_value": 380000.0,      # Position value
                "available_cash": 115000.0,    # Available for trading
                "buying_power": 115000.0,      # Max buying power
                "account_type": "stock",       # Account type
                "pnl": 12500.0,                # Today's P&L
                "pnl_ratio": 0.025             # Today's P&L ratio
            }
        """
        if not self.xt_trader or not self.acc:
            log.warning("miniQMT not connected, cannot query account")
            return {}
        
        try:
            log.debug("Querying account info from miniQMT...")
            
            # Query account assets
            # query_stock_asset(account) returns account asset object
            asset = self.xt_trader.query_stock_asset(self.acc)
            
            if not asset:
                log.warning("No account data returned from miniQMT")
                return {}

            raw_asset_fields = {}
            for name in dir(asset):
                if name.startswith("_"):
                    continue
                try:
                    value = getattr(asset, name)
                except Exception as exc:
                    raw_asset_fields[name] = f"<unreadable: {exc}>"
                    continue
                if callable(value):
                    continue
                if isinstance(value, (str, int, float, bool, type(None))):
                    raw_asset_fields[name] = value
                else:
                    raw_asset_fields[name] = repr(value)
            log.warning("DEBUG raw miniQMT asset fields: %s", raw_asset_fields)
            
            # Extract account information
            result = {
                # Core balance data
                "total_asset": float(getattr(asset, 'total_asset', 0)),
                "cash": float(getattr(asset, 'cash', 0)),
                "frozen_cash": float(getattr(asset, 'frozen_cash', 0)),
                "market_value": float(getattr(asset, 'market_value', 0)),
                "available_cash": float(getattr(asset, 'cash', 0) - getattr(asset, 'frozen_cash', 0)),
                
                # Trading power
                "buying_power": float(getattr(asset, 'cash', 0) - getattr(asset, 'frozen_cash', 0)),
                
                # Account info
                "account_type": "stock",
                "account_id": self.account_id,
                
                # P&L data (if available)
                "pnl": float(getattr(asset, 'pnl', 0)),
                "pnl_ratio": float(getattr(asset, 'pnl_ratio', 0)),
                
                # Additional fields
                "fetch_balance": float(getattr(asset, 'fetch_balance', 0)),  # 可取金额
                "interest": float(getattr(asset, 'interest', 0)),            # 利息
                "asset_balance": float(getattr(asset, 'asset_balance', 0)),  # 资产余额
            }
            
            log.info(
                "✓ Account info: Total=¥%.2f, Cash=¥%.2f, Available=¥%.2f, Market Value=¥%.2f",
                result['total_asset'],
                result['cash'],
                result['available_cash'],
                result['market_value']
            )
            
            return result
            
        except Exception as e:
            log.exception("Failed to query account from miniQMT: %s", e)
            return {}
    
    def query_orders(self) -> Dict[str, Any]:
        """Query all orders from miniQMT.
        
        Returns:
            Dict of {order_id: order_data}
        """
        if not self.xt_trader or not self.acc:
            log.warning("miniQMT not connected, cannot query orders")
            return {}
            
        try:
            from xtquant import xtconstant
            
            # Query stock orders
            orders = self.xt_trader.query_stock_orders(self.acc)
            
            result = {}
            for order in orders:
                # Map miniQMT status to our status
                # 50: 已报, 51: 废单, 52: 部成, 53: 已成, 54: 部撤, 55: 已撤, 56: 待报
                qmt_status = order.order_status
                status_msg = str(getattr(order, "status_msg", "") or "")
                order_junk = getattr(xtconstant, "ORDER_JUNK", 51)
                order_canceled = getattr(xtconstant, "ORDER_CANCELED", 55)
                order_succeeded = getattr(xtconstant, "ORDER_SUCCEEDED", 53)
                order_part_succeeded = getattr(xtconstant, "ORDER_PART_SUCCEEDED", 52)
                order_partsucc_cancel = getattr(xtconstant, "ORDER_PARTSUCC_CANCEL", 54)
                order_reported = getattr(xtconstant, "ORDER_REPORTED", 50)
                order_wait_reporting = getattr(xtconstant, "ORDER_WAIT_REPORTING", 56)
                
                status = "unknown"
                if qmt_status in [order_junk, order_canceled]: # 51, 55
                    status = "cancelled" # or rejected/failed based on msg
                    if "废单" in status_msg:
                        status = "rejected"
                elif qmt_status == order_succeeded: # 53
                    status = "filled"
                elif qmt_status == order_part_succeeded: # 52
                    status = "partial_filled"
                elif qmt_status == order_partsucc_cancel: # 54
                    status = "partial_cancelled" 
                elif qmt_status in [order_reported, order_wait_reporting]: # 50, 56
                    status = "submitted"
                
                # Convert to standard format
                order_data = {
                    "order_id": str(order.order_id),
                    "symbol": order.stock_code,
                    "action": "buy" if order.order_type == xtconstant.STOCK_BUY else "sell",
                    "status": status,
                    "order_volume": order.order_volume,
                    "price": order.price,
                    "filled_qty": order.traded_volume,  # Traded volume
                    "avg_price": order.traded_price,    # Traded price
                    "status_msg": status_msg,
                    "qmt_status": qmt_status,
                    "created_time": order.order_time,
                }
                for target, candidates in {
                    "commission": ("commission", "entrust_fee", "fee"),
                    "stamp_tax": ("stamp_tax", "stamp_duty", "tax"),
                    "transfer_fee": ("transfer_fee", "transfer_cost"),
                    "other_fee": ("other_fee", "other_cost", "handling_fee"),
                    "total_fee": ("total_fee", "fee_total", "cost", "total_cost"),
                }.items():
                    for name in candidates:
                        if hasattr(order, name):
                            value = getattr(order, name)
                            if value not in (None, ""):
                                order_data[target] = value
                                break
                result[str(order.order_id)] = order_data
                
            return result
            
        except Exception as e:
            log.exception("Failed to query orders from miniQMT: %s", e)
            return {}

    def get_execution_status(self) -> Dict[str, Dict[str, Any]]:
        """Get execution status for all tracked orders from miniQMT.

        This method queries all orders from miniQMT and returns a dictionary
        mapping broker_order_id to execution status data.

        Returns:
            Dict of {broker_order_id: {
                "status": "filled"|"rejected"|"submitted"|...,
                "filled_size": int,
                "avg_price": float,
                "msg": str
            }}
        """
        if not self.xt_trader:
            return {}
            
        try:
            # Query latest orders state
            orders = self.query_orders()
            
            result = {}
            for broker_order_id, order_data in orders.items():
                result[broker_order_id] = {
                    "status": order_data["status"],
                    "filled_size": order_data["filled_qty"],
                    "avg_price": order_data["avg_price"],
                    "msg": order_data.get("status_msg", ""),
                    "raw_status": order_data.get("qmt_status")
                }
                for key in ("commission", "stamp_tax", "transfer_fee", "other_fee", "total_fee"):
                    if key in order_data:
                        result[broker_order_id][key] = order_data[key]
            
            if result:
                log.debug("Got status for %d orders from miniQMT", len(result))
                
            return result
            
        except Exception as e:
            log.error("Error getting execution status: %s", e)
            return {}
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account metadata information.
        
        Returns:
            Dict with account metadata:
            - account_id: Broker-specific account ID
            - broker: Broker name/type
            - user_id: User ID (if applicable)
            - account_type: Account type
        """
        return {
            "account_id": self.account_id,
            "broker": "miniQMT",
            "account_type": "stock",
        }
    
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
