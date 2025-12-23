#!/usr/bin/env python3
"""Show the log file location for quantTrader.

This utility displays where quantTrader writes its log files on your system.
"""

import os
import sys
from pathlib import Path


def get_log_directory() -> Path:
    """Get platform-appropriate log directory.
    
    Returns:
        Path: Log directory path
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
    
    return log_dir


def main():
    log_dir = get_log_directory()
    log_file = log_dir / "quantTrader.log"
    
    print("=" * 60)
    print("quantTrader Log File Location")
    print("=" * 60)
    print(f"\nLog directory: {log_dir}")
    print(f"Log file:      {log_file}")
    print()
    
    if log_dir.exists():
        print("✅ Log directory exists")
        
        # List log files
        log_files = sorted(log_dir.glob("quantTrader.log*"))
        if log_files:
            print(f"\n📋 Found {len(log_files)} log file(s):")
            for f in log_files:
                size = f.stat().st_size if f.exists() else 0
                size_mb = size / (1024 * 1024)
                print(f"   - {f.name} ({size_mb:.2f} MB)")
        else:
            print("\n⚠️  No log files found yet (quantTrader hasn't been run)")
    else:
        print("⚠️  Log directory doesn't exist yet")
        print("   (will be created automatically when quantTrader runs)")
    
    print()
    print("=" * 60)
    
    # Platform-specific tips
    if sys.platform == "win32":
        print("\nTo open log directory in Explorer:")
        print(f'  explorer "{log_dir}"')
    else:
        print("\nTo view latest log:")
        print(f'  tail -f "{log_file}"')
        print("\nTo open log directory:")
        print(f'  open "{log_dir}"  # macOS')
        print(f'  xdg-open "{log_dir}"  # Linux')
    
    print()


if __name__ == "__main__":
    main()
