from __future__ import annotations

from typing import Any, Dict, List

import requests

from .config import TraderConfig


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

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------
    def get_pending_signals(self, limit: int = 50, include_submitted: bool = False) -> List[Dict[str, Any]]:
        """Fetch pending trade signals for current user.

        Only signals belonging to the authenticated user will be returned
        (enforced by backend using the token).
        """
        resp = requests.get(
            f"{self.base_url}/trader/signals",
            headers=self._headers(),
            params={"limit": limit, "include_submitted": include_submitted},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("data", []) or []
        return []

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
