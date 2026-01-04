"""Tests for cleanup_stale_positions API endpoint in TraderApiClient.

These tests validate that:
- The cleanup endpoint is called with correct parameters
- HTTP errors are properly handled
- Response data is correctly returned
- Edge cases are handled (empty symbols, None account_id, etc.)
"""

import pytest
from unittest.mock import Mock, patch
from quant_trader.api_client import TraderApiClient
from quant_trader.config import TraderConfig


class TestCleanupStalePositions:
    """Test suite for cleanup_stale_positions method."""
    
    @pytest.fixture
    def config(self):
        """Create a test config."""
        return TraderConfig(
            api_base_url="http://localhost:3001/api",
            api_token="test_token_123",
            securities_account_id="test_account_id"
        )
    
    @pytest.fixture
    def client(self, config):
        """Create API client with test config."""
        return TraderApiClient(config)
    
    def test_cleanup_with_valid_symbols(self, client):
        """Test cleanup with valid symbol list."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 3,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup
            symbols = ["600000.SH", "300001.SZ", "000001.SZ"]
            result = client.cleanup_stale_positions(symbols, account_id="ACC_X")
            
            # Verify result
            assert result["success"] is True
            assert result["deleted_count"] == 3
            
            # Verify request was made correctly
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"  # Method
            assert "/trader/positions/cleanup" in call_args[0][1]  # URL
            
            # Verify payload
            json_payload = call_args[1]["json"]
            assert json_payload["current_symbols"] == symbols
            assert json_payload["securities_account_id"] == "ACC_X"
    
    def test_cleanup_with_empty_symbols(self, client):
        """Test cleanup with empty symbol list (cleanup all)."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 5,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup with empty list
            result = client.cleanup_stale_positions([], account_id="ACC_X")
            
            # Verify result
            assert result["success"] is True
            assert result["deleted_count"] == 5
            
            # Verify payload has empty symbols list
            json_payload = mock_request.call_args[1]["json"]
            assert json_payload["current_symbols"] == []
    
    def test_cleanup_without_account_id(self, client):
        """Test cleanup without account_id filter."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 2,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup without account_id
            symbols = ["600000.SH"]
            result = client.cleanup_stale_positions(symbols, account_id=None)
            
            # Verify result
            assert result["success"] is True
            
            # Verify payload has None account_id
            json_payload = mock_request.call_args[1]["json"]
            assert json_payload["securities_account_id"] is None
    
    def test_cleanup_http_error_handling(self, client):
        """Test proper error handling for HTTP errors."""
        import requests
        
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock HTTP error
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.text = '{"detail": "Not Found"}'
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                response=mock_response
            )
            mock_request.return_value = mock_response
            
            # Should raise HTTPError
            with pytest.raises(requests.exceptions.HTTPError):
                client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
    
    def test_cleanup_network_error_handling(self, client):
        """Test error handling for network failures."""
        import requests
        
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock network error
            mock_request.side_effect = requests.exceptions.ConnectionError("Network unreachable")
            
            # Should raise ConnectionError
            with pytest.raises(requests.exceptions.ConnectionError):
                client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
    
    def test_cleanup_timeout_handling(self, client):
        """Test error handling for timeout."""
        import requests
        
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock timeout
            mock_request.side_effect = requests.exceptions.Timeout("Request timeout")
            
            # Should raise Timeout
            with pytest.raises(requests.exceptions.Timeout):
                client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
    
    def test_cleanup_request_headers(self, client):
        """Test that proper headers are sent."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 1,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup
            client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
            
            # Verify headers
            call_kwargs = mock_request.call_args[1]
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["Content-Type"] == "application/json"
            assert call_kwargs["headers"]["Authorization"] == "Bearer test_token_123"
    
    def test_cleanup_timeout_parameter(self, client):
        """Test that timeout parameter is set."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 1,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup
            client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
            
            # Verify timeout is set
            call_kwargs = mock_request.call_args[1]
            assert "timeout" in call_kwargs
            assert call_kwargs["timeout"] == 10
    
    def test_cleanup_integration_with_large_symbol_list(self, client):
        """Test cleanup with large symbol list."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 0,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Create large symbol list
            symbols = [f"{600000 + i:06d}.SH" for i in range(100)]
            result = client.cleanup_stale_positions(symbols, account_id="ACC_X")
            
            # Verify result
            assert result["success"] is True
            
            # Verify payload
            json_payload = mock_request.call_args[1]["json"]
            assert len(json_payload["current_symbols"]) == 100


class TestCleanupEdgeCases:
    """Test edge cases for cleanup functionality."""
    
    @pytest.fixture
    def config(self):
        """Create a test config."""
        return TraderConfig(
            api_base_url="http://localhost:3001/api",
            api_token="test_token_123",
            securities_account_id="test_account_id"
        )
    
    @pytest.fixture
    def client(self, config):
        """Create API client with test config."""
        return TraderApiClient(config)
    
    def test_cleanup_with_duplicate_symbols(self, client):
        """Test cleanup with duplicate symbols in list."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock successful response
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 1,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup with duplicates
            symbols = ["600000.SH", "600000.SH", "300001.SZ"]
            result = client.cleanup_stale_positions(symbols, account_id="ACC_X")
            
            # Verify result - backend should handle duplicates
            assert result["success"] is True
            
            # Verify payload contains duplicates (let backend handle dedup)
            json_payload = mock_request.call_args[1]["json"]
            assert len(json_payload["current_symbols"]) == 3
    
    def test_cleanup_response_with_no_deleted(self, client):
        """Test cleanup response when no positions were deleted."""
        with patch('quant_trader.api_client.requests.request') as mock_request:
            # Mock response with 0 deleted
            mock_response = Mock()
            mock_response.json.return_value = {
                "success": True,
                "deleted_count": 0,
                "timestamp": 1704472400.123
            }
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response
            
            # Call cleanup
            result = client.cleanup_stale_positions(["600000.SH"], account_id="ACC_X")
            
            # Verify result - still success with 0 deleted
            assert result["success"] is True
            assert result["deleted_count"] == 0
