from __future__ import annotations

import argparse
import logging
from typing import List

from .api_client import TraderApiClient
from .broker_simulated import SimulatedBroker
from .config import load_config
from .trader_loop import TraderLoop

try:
    from .broker_miniQMT import MiniQMTBroker
    MINIQMT_AVAILABLE = True
except ImportError:
    MINIQMT_AVAILABLE = False


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="quantTrader - minimal REST trader client")
    parser.add_argument(
        "--config",
        help="Path to JSON config file (optional; env vars are also supported)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    api = TraderApiClient(cfg)
    
    # Initialize broker based on config
    broker_type = getattr(cfg, 'broker', 'simulated').lower()
    
    if broker_type == 'miniqmt':
        if not MINIQMT_AVAILABLE:
            raise RuntimeError(
                "miniQMT broker not available. "
                "Make sure you're on Windows with miniQMT installed and xtquant package available."
            )
        
        # Get miniQMT config
        miniqmt_config = getattr(cfg, 'miniQMT', None)
        if not miniqmt_config:
            raise ValueError(
                "miniQMT broker selected but 'miniQMT' config not found. "
                "Add 'miniQMT': {'xt_path': '...', 'account_id': '...'} to config.json"
            )
        
        xt_path = miniqmt_config.get('xt_path')
        account_id = miniqmt_config.get('account_id')
        
        if not xt_path or not account_id:
            raise ValueError(
                "miniQMT config incomplete. Required: 'xt_path' and 'account_id'"
            )
        
        broker = MiniQMTBroker(xt_path=xt_path, account_id=account_id)
        logging.info("Using miniQMT broker: xt_path=%s, account_id=%s", xt_path, account_id)
    else:
        broker = SimulatedBroker()
        logging.info("Using simulated broker (no real trades)")
    
    loop = TraderLoop(cfg, api, broker)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nStopping quantTrader...")
        loop.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
