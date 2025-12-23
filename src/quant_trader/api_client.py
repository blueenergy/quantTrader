from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from .config import TraderConfig

log = logging.getLogger("quantTrader")


class TraderApiClient:
    """Thin REST client for quantFinance trader APIs.

    This client assumes the backend exposes the following endpoints (already implemented):
      - GET  /api/trader/signals
      - POST /api/trader/signals/{order_id}/status
      - POST /api/trader/executions
    """

    def __init__(self, cfg: TraderConfig) -> None:
        self.base_url = cfg.api_base_url.rstrip("/")
        self.token = cfg.api_token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Generic HTTP request helper.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., '/trader/account/sync')
            **kwargs: Additional arguments for requests (json, params, etc.)
            
        Returns:
            Response JSON as dict
        """
        url = f"{self.base_url}{endpoint}"
        
        # Ensure headers are included
        if 'headers' not in kwargs:
            kwargs['headers'] = self._headers()
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 10
        
        log.debug("%s %s", method, url)
        
        try:
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            log.error("HTTP error %s %s: %s - %s", method, endpoint, e.response.status_code, e.response.text)
            raise
        except Exception as e:
            log.error("Request failed %s %s: %s", method, endpoint, e)
            raise

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------
    def get_pending_signals(self, limit: int = 50, include_submitted: bool = False) -> List[Dict[str, Any]]:
        """Fetch pending trade signals for current user.

        Only signals belonging to the authenticated user will be returned
        (enforced by backend using the token).
        """
        url = f"{self.base_url}/trader/signals"
        params = {"limit": limit, "include_submitted": include_submitted}
        
        log.debug("GET %s with params=%s", url, params)
        
        try:
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, dict):
                signals = data.get("data", []) or []
                log.debug("API returned %d signals", len(signals))
                return signals
            return []
            
        except requests.exceptions.HTTPError as e:
            log.error("HTTP error fetching signals: %s - %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            log.error("Failed to fetch signals: %s", e)
            raise

    def update_signal_status(self, order_id: str, payload: Dict[str, Any]) -> None:
        """Update status of a trade signal.

        Typical uses:
          - Mark as 'submitted' with qmt_order_id
          - Mark as 'retry_pending' with last_error
          - Mark as 'failed' when retries are exhausted
        """
        resp = requests.post(
            f"{self.base_url}/trader/signals/{order_id}/status",
            headers=self._headers(),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

    def create_execution(self, execution: Dict[str, Any]) -> None:
        """Report a trade execution back to backend.

        Backend will attach user_id based on the token and update the
        corresponding trade_signals entry when appropriate.
        """
        resp = requests.post(
            f"{self.base_url}/trader/executions",
            headers=self._headers(),
            json=execution,
            timeout=10,
        )
        resp.raise_for_status()
    
    def sync_positions(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync positions to backend.
        
        Args:
            positions: List of position dicts
            
        Returns:
            Response dict with success status
        """
        return self._request(
            "POST",
            "/trader/positions/sync",
            json=positions
        )
    
    def sync_account(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync account information to backend.
        
        Args:
            account_data: Account data dict
            
        Returns:
            Response dict with success status
        """
        return self._request(
            "POST",
            "/trader/account/sync",
            json=account_data
        )
    
    def store_position_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Store daily position snapshot.
        
        Args:
            snapshot: Snapshot data dict
            
        Returns:
            Response dict with success status
        """
        return self._request(
            "POST",
            "/trader/positions/snapshot",
            json=snapshot
        )
