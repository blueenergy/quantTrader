#!/usr/bin/env python3
"""Position management CLI for quantTrader.

Tools for:
- Viewing current positions
- Analyzing portfolio risk
- Generating strategy suggestions
- Exporting data for AI analysis

Usage:
    # View all positions
    python -m quant_trader.position_cli --config config.json positions
    
    # Show portfolio summary
    python -m quant_trader.position_cli --config config.json summary
    
    # Get grid strategy suggestion for a symbol
    python -m quant_trader.position_cli --config config.json grid 000858.SZ
    
    # Analyze risk for all positions
    python -m quant_trader.position_cli --config config.json risk
    
    # Export positions for AI analysis
    python -m quant_trader.position_cli --config config.json export positions.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from quant_trader.config import load_config
from quant_trader.api_client import TraderApiClient
from quant_trader.position_manager import PositionManager

# Try to import broker
try:
    from quant_trader.broker_miniQMT import MiniQMTBroker
    MINIQMT_AVAILABLE = True
except ImportError:
    MINIQMT_AVAILABLE = False

from quant_trader.broker_simulated import SimulatedBroker


def setup_logging(level: str = "INFO"):
    """Setup console logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(message)s'
    )


def create_broker(cfg):
    """Create broker instance from config."""
    broker_type = getattr(cfg, 'broker', 'simulated').lower()
    
    if broker_type == 'miniqmt':
        if not MINIQMT_AVAILABLE:
            print("ERROR: miniQMT broker not available")
            print("Make sure you're on Windows with miniQMT installed")
            sys.exit(1)
        
        miniqmt_config = getattr(cfg, 'miniQMT', None)
        if not miniqmt_config:
            print("ERROR: miniQMT config not found in config file")
            sys.exit(1)
        
        xt_path = miniqmt_config.get('xt_path')
        account_id = miniqmt_config.get('account_id')
        
        if not xt_path or not account_id:
            print("ERROR: miniQMT config incomplete (need xt_path and account_id)")
            sys.exit(1)
        
        return MiniQMTBroker(xt_path=xt_path, account_id=account_id)
    else:
        print("WARNING: Using simulated broker (no real positions)")
        return SimulatedBroker()


def cmd_positions(manager: PositionManager, args):
    """Show all positions."""
    positions = manager.sync_positions(force=True)
    
    if not positions:
        print("No positions found")
        return
    
    print("=" * 100)
    print(f"{'Symbol':<12} {'Qty':>8} {'Avail':>8} {'Cost':>10} {'Price':>10} {'Value':>12} {'P&L':>12} {'P&L%':>8}")
    print("=" * 100)
    
    for symbol, pos in sorted(positions.items()):
        print(f"{symbol:<12} {pos.quantity:>8} {pos.available_qty:>8} "
              f"¥{pos.avg_cost:>9.2f} ¥{pos.current_price:>9.2f} "
              f"¥{pos.market_value:>11.2f} ¥{pos.unrealized_pnl:>11.2f} "
              f"{pos.unrealized_pnl_pct:>7.2f}%")
    
    print("=" * 100)


def cmd_summary(manager: PositionManager, args):
    """Show portfolio summary."""
    manager.sync_positions(force=True)
    summary = manager.get_portfolio_summary()
    
    print("\n" + "=" * 60)
    print("PORTFOLIO SUMMARY")
    print("=" * 60)
    print(f"Total Positions:  {summary['total_positions']}")
    print(f"Total Value:      ¥{summary['total_value']:,.2f}")
    print(f"Total Cost:       ¥{summary['total_cost']:,.2f}")
    print(f"Total P&L:        ¥{summary['total_pnl']:,.2f}")
    print(f"Total P&L %:      {summary['total_pnl_pct']:.2f}%")
    print(f"Last Sync:        {summary['last_sync']}")
    print("=" * 60)
    
    if summary['positions']:
        print("\nTop Positions by Value:")
        print("-" * 60)
        for i, pos in enumerate(summary['positions'][:5], 1):
            print(f"{i}. {pos['symbol']:<12} Value=¥{pos['value']:>11.2f} "
                  f"P&L={pos['pnl']:>10.2f} ({pos['pnl_pct']:>6.2f}%)")
        print()


def cmd_grid(manager: PositionManager, args):
    """Generate grid strategy suggestion for a symbol."""
    symbol = args.symbol
    
    manager.sync_positions(force=True)
    suggestion = manager.suggest_grid_strategy(symbol)
    
    if not suggestion:
        print(f"No position found for {symbol}")
        return
    
    print("\n" + "=" * 80)
    print(f"GRID STRATEGY SUGGESTION FOR {symbol}")
    print("=" * 80)
    print(f"\nCurrent Position:")
    print(f"  Quantity:        {suggestion['current_position']:,} shares")
    print(f"  Average Cost:    ¥{suggestion['current_cost']:.2f}")
    print(f"  Current Price:   ¥{suggestion['current_price']:.2f}")
    print(f"  Unrealized P&L:  {suggestion['unrealized_pnl_pct']:+.2f}%")
    
    print(f"\nSuggested Grid Parameters:")
    print(f"  Number of Grids:     {suggestion['suggested_grids']}")
    print(f"  Grid Spacing:        {suggestion['grid_spacing_pct']:.1f}%")
    print(f"  Buy Grid Size:       {suggestion['buy_grid_size']:,} shares")
    print(f"  Sell Grid Size:      {suggestion['sell_grid_size']:,} shares")
    
    print(f"\nExpected Outcome:")
    print(f"  Target Cost:         ¥{suggestion['target_cost']:.2f}")
    print(f"  Cost Reduction:      {suggestion['cost_reduction_target_pct']:.1f}%")
    print(f"  Max Position:        {suggestion['max_position']:,} shares")
    print(f"  Estimated Duration:  {suggestion['estimated_days']} days")
    
    print(f"\nDescription:")
    print(f"  {suggestion['description']}")
    print("=" * 80)
    print()


def cmd_risk(manager: PositionManager, args):
    """Analyze risk for all positions."""
    manager.sync_positions(force=True)
    positions = manager.get_all_positions()
    
    if not positions:
        print("No positions found")
        return
    
    print("\n" + "=" * 100)
    print("RISK ANALYSIS")
    print("=" * 100)
    print(f"{'Symbol':<12} {'Concentration':>14} {'Drawdown':>10} {'Liquidity Risk':>15} {'Risk Score':>12}")
    print("=" * 100)
    
    for symbol in sorted(positions.keys()):
        risk = manager.analyze_position_risk(symbol)
        if risk:
            print(f"{symbol:<12} {risk['concentration_pct']:>13.2f}% "
                  f"{risk['drawdown_pct']:>9.2f}% {risk['liquidity_risk_pct']:>14.2f}% "
                  f"{risk['risk_score']:>11.0f}/100")
    
    print("=" * 100)
    print()


def cmd_export(manager: PositionManager, args):
    """Export positions for AI analysis."""
    output_file = args.output
    
    manager.sync_positions(force=True)
    positions = manager.get_all_positions()
    summary = manager.get_portfolio_summary()
    
    # Build export data
    export_data = {
        "timestamp": summary["last_sync"],
        "portfolio_summary": {
            "total_positions": summary["total_positions"],
            "total_value": summary["total_value"],
            "total_cost": summary["total_cost"],
            "total_pnl": summary["total_pnl"],
            "total_pnl_pct": summary["total_pnl_pct"]
        },
        "positions": [pos.to_dict() for pos in positions.values()],
        "risk_analysis": [
            manager.analyze_position_risk(symbol)
            for symbol in positions.keys()
        ]
    }
    
    # Write to file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Exported {len(positions)} positions to {output_file}")


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="quantTrader Position Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--config',
        help='Path to config.json file'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # positions command
    subparsers.add_parser('positions', help='Show all positions')
    
    # summary command
    subparsers.add_parser('summary', help='Show portfolio summary')
    
    # grid command
    parser_grid = subparsers.add_parser('grid', help='Generate grid strategy suggestion')
    parser_grid.add_argument('symbol', help='Stock symbol (e.g., 000858.SZ)')
    
    # risk command
    subparsers.add_parser('risk', help='Analyze position risk')
    
    # export command
    parser_export = subparsers.add_parser('export', help='Export positions for AI analysis')
    parser_export.add_argument('output', help='Output JSON file')
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return
    
    # Load config
    cfg = load_config(args.config)
    setup_logging(cfg.log_level)
    
    # Create components
    api = TraderApiClient(cfg)
    broker = create_broker(cfg)
    manager = PositionManager(api_client=api, broker=broker, sync_interval=0)
    
    # Execute command
    try:
        if args.command == 'positions':
            cmd_positions(manager, args)
        elif args.command == 'summary':
            cmd_summary(manager, args)
        elif args.command == 'grid':
            cmd_grid(manager, args)
        elif args.command == 'risk':
            cmd_risk(manager, args)
        elif args.command == 'export':
            cmd_export(manager, args)
    finally:
        broker.close()


if __name__ == '__main__':
    main()
