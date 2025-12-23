from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
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


def _get_log_directory() -> Path:
    """Get platform-appropriate log directory.
    
    Returns:
        Path: Log directory path (created if doesn't exist)
        
    Platform-specific locations:
    - Linux/macOS: ~/.local/share/quantTrader/logs/
    - Windows: %LOCALAPPDATA%\quantTrader\logs\
    """
    if sys.platform == "win32":
        # Windows: %LOCALAPPDATA%\quantTrader\logs
        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = os.path.expanduser("~\\AppData\\Local")
        log_dir = Path(base) / "quantTrader" / "logs"
    else:
        # Linux/macOS: ~/.local/share/quantTrader/logs
        base = os.getenv("XDG_DATA_HOME")
        if not base:
            base = os.path.expanduser("~/.local/share")
        log_dir = Path(base) / "quantTrader" / "logs"
    
    # Create directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _setup_logging(cfg) -> None:
    """Setup logging with both console and file handlers.
    
    Logs are written to:
    - Console (stdout)
    - File: <log_dir>/quantTrader.log (rotating, max 10MB, 5 backups)
    """
    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler with rotation
    try:
        log_dir = _get_log_directory()
        log_file = log_dir / "quantTrader.log"
        
        # Rotating file handler: max 10MB per file, keep 5 backup files
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Log the log file location at startup
        logging.info("quantTrader logging initialized")
        logging.info("Log file: %s", log_file)
        logging.info("Log level: %s", cfg.log_level.upper())
        
    except Exception as e:
        # If file logging fails, just log to console
        logging.warning("Failed to setup file logging: %s. Using console only.", e)


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="quantTrader - minimal REST trader client")
    parser.add_argument(
        "--config",
        help="Path to JSON config file (optional; env vars are also supported)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    # Setup logging with file output
    _setup_logging(cfg)

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
