"""Position Manager for quantTrader.

Provides comprehensive position management capabilities:
- Real-time position synchronization from broker
- Position cost tracking and P&L calculation
- Historical position analysis
- Strategy integration on existing positions
- Data foundation for AI-driven analysis

Design Philosophy:
This is a strategic component that enables:
1. Full control over portfolio positions
2. Cost-reduction grid strategies on existing holdings
3. AI-powered position and trade history analysis
4. Multi-strategy overlay on same positions
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)


@dataclass
class AccountInfo:
    """Account information snapshot.
    
    Attributes:
        total_asset: Total account value (cash + positions)
        cash: Total cash balance
        frozen_cash: Cash frozen in pending orders
        market_value: Total market value of positions
        available_cash: Cash available for trading
        buying_power: Maximum buying power
        account_type: Account type (stock/margin)
        account_id: Trading account ID
        pnl: Today's profit/loss
        pnl_ratio: Today's P&L ratio
        last_updated: Timestamp of last sync
    """
    total_asset: float
    cash: float
    frozen_cash: float
    market_value: float
    available_cash: float
    buying_power: float
    account_type: str
    account_id: str
    pnl: float = 0.0
    pnl_ratio: float = 0.0
    last_updated: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AccountInfo:
        """Create AccountInfo from dictionary."""
        return cls(**data)


@dataclass
class Position:
    """Real-time position snapshot from broker.
    
    Attributes:
        symbol: Stock symbol (e.g., "000858.SZ")
        quantity: Total shares held
        available_qty: Shares available to sell (not frozen)
        frozen_qty: Shares frozen in pending orders
        avg_cost: Average cost per share
        market_value: Current market value
        current_price: Latest market price
        unrealized_pnl: Unrealized profit/loss
        unrealized_pnl_pct: Unrealized P&L percentage
        holding_days: Days since first purchase
        last_updated: Timestamp of last sync
        broker: Broker company name (e.g., "国金证券"), filled by backend from securities_accounts
        account_id: Trading account ID at the broker
    """
    symbol: str
    quantity: int
    available_qty: int
    frozen_qty: int
    avg_cost: float
    market_value: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    holding_days: int
    last_updated: float
    broker: str
    account_id: str
    
    # Extended metadata for AI analysis
    first_buy_date: Optional[float] = None
    last_trade_date: Optional[float] = None
    total_trades: int = 0
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    realized_pnl: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Position:
        """Create Position from dictionary."""
        return cls(**data)


class PositionManager:
    """Manages position synchronization and analysis.
    
    Features:
    1. Real-time sync from broker (miniQMT)
    2. Position persistence to MongoDB
    3. Cost tracking and P&L calculation
    4. Historical position snapshots
    5. Position-based strategy suggestions
    
    Usage:
        manager = PositionManager(api_client, broker)
        
        # Sync positions from broker
        positions = manager.sync_positions()
        
        # Get position details
        position = manager.get_position("000858.SZ")
        
        # Analyze position for grid strategy opportunities
        suggestions = manager.suggest_grid_strategy(position)
    """
    
    def __init__(
        self,
        api_client: Any,  # TraderApiClient
        broker: Optional[Any] = None,  # BrokerAdapter
        sync_interval: float = 60.0
    ) -> None:
        """Initialize PositionManager.
        
        Args:
            api_client: TraderApiClient for backend communication
            broker: BrokerAdapter for querying broker positions
            sync_interval: Seconds between automatic syncs (default: 60s)
        """
        self.api = api_client
        self.broker = broker
        self.sync_interval = sync_interval
        
        # Get broker account info from broker adapter
        self.broker_account_id = getattr(broker, 'account_id', 'unknown') if broker else 'unknown'
        
        # Local position cache
        self._positions: Dict[str, Position] = {}
        self._last_sync_time = 0
        
        # Account info cache
        self._account_info: Optional[AccountInfo] = None
        self._last_account_sync = 0
        
        log.info("PositionManager initialized: sync_interval=%.1fs", sync_interval)
    
    def sync_positions(self, force: bool = False) -> Dict[str, Position]:
        """Sync positions from broker to local cache and backend.
        
        Args:
            force: Force sync even if within sync interval
            
        Returns:
            Dictionary of {symbol: Position}
            
        Workflow:
            1. Check if sync needed (rate limiting)
            2. Query broker for current positions
            3. Calculate P&L and enrichments
            4. Update local cache
            5. Push to backend API
            6. Store historical snapshot
        """
        current_time = time.time()
        
        # Rate limiting
        if not force and (current_time - self._last_sync_time < self.sync_interval):
            log.debug("Skipping position sync (within interval)")
            return self._positions
        
        if not self.broker:
            log.warning("No broker configured, cannot sync positions")
            return self._positions
        
        try:
            # Query positions from broker
            broker_positions = self._query_broker_positions()
            
            if not broker_positions:
                log.info("No positions found in broker account")
                self._positions = {}
                self._last_sync_time = current_time
                return self._positions
            
            # Process each position
            positions = {}
            for symbol, pos_data in broker_positions.items():
                position = self._create_position(symbol, pos_data)
                positions[symbol] = position
                
                log.info(
                    "Position synced: %s qty=%d cost=%.2f value=%.2f pnl=%.2f (%.2f%%)",
                    symbol,
                    position.quantity,
                    position.avg_cost,
                    position.market_value,
                    position.unrealized_pnl,
                    position.unrealized_pnl_pct
                )
            
            # Update cache
            self._positions = positions
            self._last_sync_time = current_time
            
            # Push to backend
            self._push_to_backend(positions)
            
            # Store historical snapshot
            self._store_snapshot(positions)
            
            log.info("✓ Position sync complete: %d positions", len(positions))
            return positions
            
        except Exception as e:
            log.exception("Failed to sync positions: %s", e)
            return self._positions
    
    def sync_account(self, force: bool = False) -> Optional[AccountInfo]:
        """Sync account information from broker.
        
        Args:
            force: Force sync even if within sync interval
            
        Returns:
            AccountInfo object or None if sync failed
            
        Workflow:
            1. Check if sync needed (rate limiting)
            2. Query broker for account data
            3. Create AccountInfo object
            4. Update local cache
            5. Push to backend API
        """
        current_time = time.time()
        
        # Rate limiting
        if not force and (current_time - self._last_account_sync < self.sync_interval):
            log.debug("Skipping account sync (within interval)")
            return self._account_info
        
        if not self.broker:
            log.warning("No broker configured, cannot sync account")
            return self._account_info
        
        try:
            # Query account from broker
            account_data = self._query_broker_account()
            
            if not account_data:
                log.warning("No account data returned from broker")
                self._last_account_sync = current_time
                return self._account_info
            
            # Create AccountInfo object
            account_info = AccountInfo(
                total_asset=account_data.get('total_asset', 0),
                cash=account_data.get('cash', 0),
                frozen_cash=account_data.get('frozen_cash', 0),
                market_value=account_data.get('market_value', 0),
                available_cash=account_data.get('available_cash', 0),
                buying_power=account_data.get('buying_power', 0),
                account_type=account_data.get('account_type', 'stock'),
                account_id=account_data.get('account_id', 'unknown'),
                pnl=account_data.get('pnl', 0),
                pnl_ratio=account_data.get('pnl_ratio', 0),
                last_updated=current_time
            )
            
            # Update cache
            self._account_info = account_info
            self._last_account_sync = current_time
            
            log.info(
                "✓ Account synced: Total=¥%.2f, Cash=¥%.2f, Available=¥%.2f, Market=¥%.2f, P&L=¥%.2f (%.2f%%)",
                account_info.total_asset,
                account_info.cash,
                account_info.available_cash,
                account_info.market_value,
                account_info.pnl,
                account_info.pnl_ratio * 100
            )
            
            # Push to backend (optional)
            self._push_account_to_backend(account_info)
            
            return account_info
            
        except Exception as e:
            log.exception("Failed to sync account: %s", e)
            return self._account_info
    
    def _query_broker_account(self) -> Dict[str, Any]:
        """Query account information from broker adapter.
        
        Returns:
            Dict with account data or empty dict if not supported
        """
        # Check if broker has query_account method
        if not hasattr(self.broker, 'query_account'):
            log.debug("Broker does not support account queries")
            return {}
        
        try:
            account_data = self.broker.query_account()
            return account_data if account_data else {}
        except Exception as e:
            log.exception("Broker account query failed: %s", e)
            return {}
    
    def _push_account_to_backend(self, account_info: AccountInfo) -> None:
        """Push account info to backend API.
        
        Args:
            account_info: AccountInfo object to push
        """
        try:
            # Push to backend API
            account_dict = account_info.to_dict()
            
            response = self.api.sync_account(account_dict)
            
            if response.get("success"):
                log.debug("Account info synced to backend")
            else:
                log.warning("Backend returned non-success for account sync")
                
        except Exception as e:
            log.warning("Failed to push account to backend: %s", e)
    
    def _query_broker_positions(self) -> Dict[str, Dict[str, Any]]:
        """Query positions from broker adapter.
        
        Returns:
            Dict of {symbol: position_data}
            
        For miniQMT, position_data includes:
            - can_use_volume: Available quantity
            - volume: Total quantity
            - frozen_volume: Frozen quantity
            - open_price: Average cost
            - market_value: Current value
            - last_price: Current price
        """
        # Check if broker has query_positions method
        if not hasattr(self.broker, 'query_positions'):
            log.error("Broker does not support position queries")
            return {}
        
        try:
            positions = self.broker.query_positions()
            return positions if positions else {}
        except Exception as e:
            log.exception("Broker query failed: %s", e)
            return {}
    
    def _create_position(self, symbol: str, broker_data: Dict[str, Any]) -> Position:
        """Create Position object from broker data.
        
        Args:
            symbol: Stock symbol
            broker_data: Raw position data from broker
            
        Returns:
            Position object with calculated fields
            
        Note:
            The 'broker' and 'account_id' fields will be filled by backend
            based on securities_account_id when syncing to database.
            Here we just use placeholder values from broker adapter.
        """
        # Extract basic fields (miniQMT format)
        quantity = int(broker_data.get('volume', 0))
        available_qty = int(broker_data.get('can_use_volume', 0))
        frozen_qty = int(broker_data.get('frozen_volume', 0))
        avg_cost = float(broker_data.get('open_price', 0))
        market_value = float(broker_data.get('market_value', 0))
        current_price = float(broker_data.get('last_price', avg_cost))
        
        # Calculate P&L
        cost_basis = avg_cost * quantity
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
        
        # Use broker account_id from adapter
        # Note: broker name will be filled by backend from securities_accounts table
        account_id = self.broker_account_id
        
        # Create position
        position = Position(
            symbol=symbol,
            quantity=quantity,
            available_qty=available_qty,
            frozen_qty=frozen_qty,
            avg_cost=avg_cost,
            market_value=market_value,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            holding_days=0,  # TODO: Calculate from trade history
            last_updated=time.time(),
            broker='',  # Will be filled by backend from securities_accounts
            account_id=account_id
        )
        
        # Enrich with historical data if available
        self._enrich_position_history(position)
        
        return position
    
    def _enrich_position_history(self, position: Position) -> None:
        """Enrich position with historical trade data.
        
        This queries backend for:
        - First buy date
        - Last trade date
        - Total number of trades
        - Total buy/sell amounts
        - Realized P&L
        
        Args:
            position: Position object to enrich (modified in-place)
        """
        try:
            # Query trade history from backend
            # TODO: Implement API endpoint for trade history query
            # history = self.api.get_trade_history(symbol=position.symbol)
            
            # For now, skip enrichment
            pass
            
        except Exception as e:
            log.debug("Failed to enrich position history: %s", e)
    
    def _push_to_backend(self, positions: Dict[str, Position]) -> None:
        """Push positions to backend API.
        
        Stores positions in backend for:
        - Cross-device access
        - Historical analysis
        - Strategy integration
        - AI analysis pipeline
        
        Args:
            positions: Dictionary of positions to push
        """
        try:
            # Convert positions to API format
            positions_data = [pos.to_dict() for pos in positions.values()]
            
            # Push to backend
            response = self.api.sync_positions(positions_data)
            
            if response.get("success"):
                log.debug("Synced %d positions to backend", len(positions_data))
            else:
                log.warning("Backend returned non-success for position sync")
            
        except Exception as e:
            log.warning("Failed to push positions to backend: %s", e)
    
    def _store_snapshot(self, positions: Dict[str, Position]) -> None:
        """Store historical position snapshot.
        
        Creates daily snapshots for:
        - P&L tracking over time
        - Portfolio performance analysis
        - AI training data
        
        Args:
            positions: Dictionary of positions to snapshot
        """
        try:
            # Create snapshot document
            snapshot = {
                'timestamp': time.time(),
                'date': datetime.now().strftime('%Y-%m-%d'),
                'positions': [pos.to_dict() for pos in positions.values()],
                'total_value': sum(pos.market_value for pos in positions.values()),
                'total_pnl': sum(pos.unrealized_pnl for pos in positions.values())
            }
            
            # Store snapshot to backend
            response = self.api.store_position_snapshot(snapshot)
            
            if response.get("success"):
                log.debug("Stored position snapshot: %s", snapshot['date'])
            else:
                log.warning("Backend returned non-success for snapshot storage")
            
        except Exception as e:
            log.warning("Failed to store position snapshot: %s", e)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get cached position for symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position object or None if not found
        """
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all cached positions.
        
        Returns:
            Dictionary of {symbol: Position}
        """
        return self._positions.copy()
    
    def suggest_grid_strategy(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Suggest grid strategy parameters for existing position.
        
        Analyzes current position and suggests grid parameters to:
        - Reduce average cost through buying dips
        - Capture profits through selling rallies
        - Manage downside risk
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Grid strategy suggestion dict or None
            
        Example:
            {
                "strategy": "grid",
                "symbol": "000858.SZ",
                "current_position": 1000,
                "current_cost": 42.50,
                "suggested_grids": 10,
                "grid_spacing": 0.05,  # 5%
                "buy_grid_size": 100,
                "sell_grid_size": 100,
                "target_cost": 40.00,
                "max_position": 1500,
                "estimated_days": 30
            }
        """
        position = self.get_position(symbol)
        if not position:
            log.warning("No position found for %s", symbol)
            return None
        
        # Calculate grid parameters
        current_price = position.current_price
        avg_cost = position.avg_cost
        quantity = position.quantity
        
        # Suggest 5% grid spacing
        grid_spacing = 0.05
        num_grids = 10
        
        # Size each grid at 10% of current position
        grid_size = max(100, quantity // 10)
        
        # Target: reduce cost by 5%
        target_cost = avg_cost * 0.95
        
        # Max position: 1.5x current
        max_position = int(quantity * 1.5)
        
        suggestion = {
            "strategy": "grid",
            "symbol": symbol,
            "current_position": quantity,
            "current_cost": avg_cost,
            "current_price": current_price,
            "unrealized_pnl_pct": position.unrealized_pnl_pct,
            "suggested_grids": num_grids,
            "grid_spacing_pct": grid_spacing * 100,
            "buy_grid_size": grid_size,
            "sell_grid_size": grid_size,
            "target_cost": target_cost,
            "max_position": max_position,
            "cost_reduction_target_pct": 5.0,
            "estimated_days": 30,
            "description": (
                f"Grid strategy to reduce cost from ¥{avg_cost:.2f} to ¥{target_cost:.2f} "
                f"by buying {grid_size} shares on {grid_spacing*100:.0f}% dips "
                f"and selling on rallies"
            )
        }
        
        log.info("Grid strategy suggestion for %s: %s", symbol, suggestion["description"])
        return suggestion
    
    def suggest_position_size(self, symbol: str, target_price: float) -> Optional[Dict[str, Any]]:
        """Suggest position size based on available cash and risk management.
        
        Uses Kelly Criterion and risk management rules to suggest:
        - Maximum position size
        - Recommended position size
        - Risk-adjusted size
        
        Args:
            symbol: Stock symbol
            target_price: Intended purchase price
            
        Returns:
            Position size suggestion dict or None
            
        Example:
            {
                "symbol": "000858.SZ",
                "target_price": 42.50,
                "available_cash": 115000.0,
                "max_shares": 2700,              # 100% cash
                "recommended_shares": 800,       # 30% cash (conservative)
                "risk_adjusted_shares": 1000,    # Based on portfolio concentration
                "estimated_cost": 42500.0,
                "cash_usage_pct": 30.0,
                "concentration_after": 15.2,     # % of portfolio
                "risk_level": "medium"
            }
        """
        # Get account info
        account = self._account_info
        if not account:
            account = self.sync_account(force=True)
            if not account:
                log.warning("No account info available")
                return None
        
        available_cash = account.available_cash
        total_asset = account.total_asset
        
        if available_cash <= 0:
            log.warning("No available cash for %s", symbol)
            return None
        
        # Calculate maximum shares based on cash
        max_shares = int(available_cash / target_price)
        
        # Round down to nearest 100 (standard lot)
        max_shares = (max_shares // 100) * 100
        
        if max_shares == 0:
            log.warning("Insufficient cash to buy even 100 shares of %s at ¥%.2f", symbol, target_price)
            return None
        
        # Conservative: use 30% of available cash
        recommended_shares = int(max_shares * 0.3)
        recommended_shares = (recommended_shares // 100) * 100
        
        # Risk-adjusted: consider portfolio concentration
        # Target: no single position > 20% of portfolio
        target_concentration = 0.15  # 15%
        risk_adjusted_value = total_asset * target_concentration
        risk_adjusted_shares = int(risk_adjusted_value / target_price)
        risk_adjusted_shares = (risk_adjusted_shares // 100) * 100
        
        # Use the smaller of recommended and risk-adjusted
        final_shares = min(recommended_shares, risk_adjusted_shares)
        final_shares = max(final_shares, 100)  # At least 100 shares
        
        estimated_cost = final_shares * target_price
        cash_usage_pct = (estimated_cost / available_cash) * 100
        
        # Calculate concentration after purchase
        new_position_value = final_shares * target_price
        new_total_value = total_asset  # Assumes cash converted to position
        concentration_after = (new_position_value / new_total_value) * 100
        
        # Determine risk level
        if concentration_after > 20:
            risk_level = "high"
        elif concentration_after > 10:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        suggestion = {
            "symbol": symbol,
            "target_price": target_price,
            "available_cash": available_cash,
            "max_shares": max_shares,
            "recommended_shares": final_shares,
            "estimated_cost": estimated_cost,
            "cash_usage_pct": cash_usage_pct,
            "concentration_after": concentration_after,
            "risk_level": risk_level,
            "rationale": (
                f"Buy {final_shares:,} shares of {symbol} at ¥{target_price:.2f} "
                f"using {cash_usage_pct:.1f}% of available cash (¥{estimated_cost:,.2f}). "
                f"Post-purchase concentration: {concentration_after:.1f}% ({risk_level} risk)."
            )
        }
        
        log.info("Position size suggestion: %s", suggestion["rationale"])
        return suggestion
    
    def analyze_position_risk(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Analyze risk metrics for position.
        
        Calculates:
        - Concentration risk (position size vs portfolio)
        - Drawdown risk (current loss percentage)
        - Liquidity risk (frozen shares ratio)
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Risk analysis dict or None
        """
        position = self.get_position(symbol)
        if not position:
            return None
        
        total_value = sum(pos.market_value for pos in self._positions.values())
        
        analysis = {
            "symbol": symbol,
            "concentration_pct": (position.market_value / total_value * 100) if total_value > 0 else 0,
            "drawdown_pct": -position.unrealized_pnl_pct if position.unrealized_pnl_pct < 0 else 0,
            "liquidity_risk_pct": (position.frozen_qty / position.quantity * 100) if position.quantity > 0 else 0,
            "risk_score": 0.0  # TODO: Calculate composite risk score
        }
        
        # Simple risk score (0-100)
        risk_score = 0
        if analysis["concentration_pct"] > 30:
            risk_score += 30
        if analysis["drawdown_pct"] > 10:
            risk_score += 40
        if analysis["liquidity_risk_pct"] > 20:
            risk_score += 30
        
        analysis["risk_score"] = min(risk_score, 100)
        
        return analysis
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio-level summary statistics.
        
        Returns:
            Dict with portfolio metrics
        """
        if not self._positions:
            return {
                "total_positions": 0,
                "total_value": 0.0,
                "total_cost": 0.0,
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "last_sync": datetime.fromtimestamp(self._last_sync_time).isoformat() if self._last_sync_time else None,
                "positions": []
            }
        
        total_value = sum(pos.market_value for pos in self._positions.values())
        total_cost = sum(pos.avg_cost * pos.quantity for pos in self._positions.values())
        total_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        return {
            "total_positions": len(self._positions),
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "last_sync": datetime.fromtimestamp(self._last_sync_time).isoformat(),
            "positions": [
                {
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "value": pos.market_value,
                    "pnl": pos.unrealized_pnl,
                    "pnl_pct": pos.unrealized_pnl_pct
                }
                for pos in sorted(
                    self._positions.values(),
                    key=lambda p: p.market_value,
                    reverse=True
                )
            ]
        }
