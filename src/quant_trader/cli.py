from __future__ import annotations

import argparse
import logging
from typing import List

from .api_client import TraderApiClient
from .broker_simulated import SimulatedBroker
from .config import load_config
from .trader_loop import TraderLoop


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
    broker = SimulatedBroker()
    loop = TraderLoop(cfg, api, broker)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nStopping quantTrader...")
        loop.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
