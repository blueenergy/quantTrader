#!/usr/bin/env python
"""
Helper script to insert a test trade signal into MongoDB for e2e testing.

Usage:
    python insert_test_signal.py [--user-id USER_ID] [--symbol SYMBOL] [--action ACTION]

Environment:
    MONGO_URI: MongoDB connection string (default: mongodb://localhost:27017)
    MONGO_DB: Database name (default: quant_finance)
"""

import argparse
import os
import json
from datetime import datetime
from pymongo import MongoClient


def insert_test_signal(
    user_id: str = None,
    symbol: str = "000858.SZ",
    action: str = "BUY",
    size: int = 100,
    price: float = 15.5,
    strategy: str = "test_strategy",
    strategy_name: str = "Test E2E Strategy",
) -> str:
    """
    Insert a test trade signal into MongoDB.
    
    Returns:
        order_id of the inserted signal
    """
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.getenv("MONGO_DB", "quant_finance")
    
    if not user_id:
        print("Error: user_id is required")
        print("  Set MONGO_USER_ID env var or pass --user-id argument")
        print("  Or create a config.json and I'll read it from there")
        raise ValueError("user_id required")
    
    client = MongoClient(mongo_uri)
    db = client[mongo_db]
    signals = db["trade_signals"]
    
    # Generate order ID
    timestamp = int(datetime.utcnow().timestamp() * 1000)
    order_id = f"TEST-E2E-{timestamp}"
    
    # Create signal document
    signal = {
        "order_id": order_id,
        "user_id": user_id,
        "symbol": symbol,
        "action": action,
        "size": size,
        "price": price,
        "strategy": strategy,
        "strategy_name": strategy_name,
        "status": "pending",
        "is_executable": True,
        "mode": "live",
        "broker": "simulated",
        "securities_account_id": "SA-001",
        "account_id": "ACC-001",
        "created_at": datetime.utcnow().timestamp(),
        "updated_at": datetime.utcnow().timestamp(),
    }
    
    result = signals.insert_one(signal)
    print(f"✓ Inserted test signal:")
    print(f"  order_id: {order_id}")
    print(f"  user_id: {user_id}")
    print(f"  symbol: {symbol}")
    print(f"  action: {action}")
    print(f"  size: {size}")
    print(f"  price: {price}")
    print(f"  strategy: {strategy}")
    print(f"\nStart quantTrader to process this signal:")
    print(f"  python -m quant_trader.cli --config config.json")
    
    return order_id


def main():
    parser = argparse.ArgumentParser(
        description="Insert a test trade signal into MongoDB for e2e testing"
    )
    parser.add_argument(
        "--user-id",
        required=False,
        help="User ID (can also set MONGO_USER_ID env var)",
    )
    parser.add_argument(
        "--symbol",
        default="000858.SZ",
        help="Stock symbol (default: 000858.SZ)",
    )
    parser.add_argument(
        "--action",
        default="BUY",
        choices=["BUY", "SELL"],
        help="Order action (default: BUY)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=100,
        help="Order size (default: 100)",
    )
    parser.add_argument(
        "--price",
        type=float,
        default=15.5,
        help="Order price (default: 15.5)",
    )
    parser.add_argument(
        "--strategy",
        default="test_strategy",
        help="Strategy name (default: test_strategy)",
    )
    parser.add_argument(
        "--from-config",
        help="Read user_id from config.json file",
    )
    
    args = parser.parse_args()
    
    user_id = args.user_id or os.getenv("MONGO_USER_ID")
    
    # Try reading from config if provided
    if args.from_config and os.path.exists(args.from_config):
        try:
            with open(args.from_config, "r") as f:
                config = json.load(f)
                # config.json doesn't have user_id, but we could add it
                print(f"Loaded config from {args.from_config}")
                print("Note: config.json doesn't contain user_id")
                print("You must provide --user-id or set MONGO_USER_ID env var")
        except Exception as e:
            print(f"Failed to read config: {e}")
    
    if not user_id:
        print("Error: user_id not found")
        print("\nUsage:")
        print("  1. Set env var: export MONGO_USER_ID='<your-user-id>'")
        print("  2. Or pass argument: python insert_test_signal.py --user-id '<your-user-id>'")
        print("\nTo find your user_id:")
        print("  - Check login response from /api/user/login")
        print("  - Or check MongoDB: db.users.findOne({username: 'your_username'})")
        exit(1)
    
    insert_test_signal(
        user_id=user_id,
        symbol=args.symbol,
        action=args.action,
        size=args.size,
        price=args.price,
        strategy=args.strategy,
        strategy_name=args.strategy,
    )


if __name__ == "__main__":
    main()
