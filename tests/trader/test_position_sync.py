"""Tests for EnhancedPositionManager functionality in quantTrader.

These tests validate that:
- Positions are properly synced from broker to backend with metadata
- Stale positions are cleaned up
- Account metadata is properly included in position records
"""

from unittest.mock import Mock
from quant_trader.execution_tracker import EnhancedPositionManager


class FakeApiClient:
    """Fake API client for testing."""
    
    def __init__(self):
        self.position_updates = []
        self.cleanup_calls = []
        self.sync_calls = []
    
    def sync_positions(self, positions):
        """Sync positions batch (matches TraderApiClient interface)."""
        self.sync_calls.append({"positions": positions})
        return {"success": True, "synced_count": len(positions)}
    
    def update_position(self, position_data):
        """Update single position (legacy method)."""
        self.position_updates.append(position_data)
        return {"status": "success"}
    
    def cleanup_stale_positions(self, current_symbols, account_id=None):
        """Cleanup stale positions (matches TraderApiClient interface)."""
        self.cleanup_calls.append({
            "current_symbols": current_symbols,
            "account_id": account_id
        })
        return {"success": True, "deleted_count": 2}


class FakeBroker:
    """Fake broker for testing."""
    
    def __init__(self):
        self.positions = {}
        self.account_info = {
            "account_id": "ACC_X",
            "broker": "test_broker"
        }
    
    def query_positions(self):
        """Query positions from broker (matches BrokerAdapter interface)."""
        return self.positions
    
    def get_account_info(self):
        """Get account info from broker (matches BrokerAdapter interface)."""
        return self.account_info


def test_sync_positions_with_metadata():
    """Test position sync with account metadata."""
    api = FakeApiClient()
    broker = FakeBroker()
    
    # Setup broker positions
    broker.positions = {
        "002050.SZ": {
            "qty": 1000,
            "can_use_volume": 800,
            "frozen_volume": 0,
            "avg_price": 10.5,
            "market_value": 10500.0,
            "on_road_volume": 0,
            "yesterday_volume": 1000,
        },
        "600036.SH": {
            "qty": 500,
            "can_use_volume": 500,
            "frozen_volume": 0,
            "avg_price": 25.0,
            "market_value": 12500.0,
            "on_road_volume": 0,
            "yesterday_volume": 500,
        }
    }
    
    manager = EnhancedPositionManager(
        api_client=api,
        broker=broker,
        sync_interval=0.1  # Very short interval for testing
    )
    
    # Perform sync
    success = manager.sync_positions()
    
    # Verify success
    assert success is True
    assert len(api.sync_calls) == 1
    
    # Check synced positions
    synced_positions = api.sync_calls[0]["positions"]
    assert len(synced_positions) == 2
    
    # Check first position
    pos1 = synced_positions[0]
    assert pos1["symbol"] == "002050"  # Should strip exchange suffix
    assert pos1["qty"] == 1000
    assert pos1["account_id"] == "ACC_X"
    assert pos1["broker"] == "test_broker"
    
    # Check second position
    pos2 = synced_positions[1]
    assert pos2["symbol"] == "600036"  # Should strip exchange suffix
    assert pos2["qty"] == 500
    assert pos2["account_id"] == "ACC_X"
    assert pos2["broker"] == "test_broker"


def test_stale_position_cleanup():
    """Test cleanup of stale positions."""
    api = FakeApiClient()
    broker = FakeBroker()
    
    # Setup broker positions (only one position)
    broker.positions = {
        "002050.SZ": {
            "qty": 1000,
            "can_use_volume": 800,
            "frozen_volume": 0,
            "avg_price": 10.5,
            "market_value": 10500.0,
            "on_road_volume": 0,
            "yesterday_volume": 1000,
        }
    }
    
    manager = EnhancedPositionManager(
        api_client=api,
        broker=broker,
        sync_interval=0.1
    )
    
    # Perform sync
    manager.sync_positions()
    
    # Verify cleanup was called with current symbols
    assert len(api.cleanup_calls) == 1
    cleanup_call = api.cleanup_calls[0]
    assert cleanup_call["current_symbols"] == ["002050"]
    assert cleanup_call["account_id"] == "ACC_X"


def test_empty_positions_sync():
    """Test sync with no positions."""
    api = FakeApiClient()
    broker = FakeBroker()
    
    # No positions
    broker.positions = {}
    
    manager = EnhancedPositionManager(
        api_client=api,
        broker=broker,
        sync_interval=0.1
    )
    
    # Perform sync
    success = manager.sync_positions()
    
    # Should still succeed but with no updates
    assert success is True
    assert len(api.position_updates) == 0
    assert len(api.cleanup_calls) == 1  # Cleanup should still be called