# quantTrader

A minimal, REST-based distributed trader client for the quantFinance trading framework.

## Overview

**quantTrader** is an independent trader application that connects to the quantFinance backend via RESTful APIs. It fetches trading signals, executes trades via a configurable broker adapter, and reports execution results back to the backend—all without direct database access.

### Key Features

- **RESTful API Integration**: Communicates with quantFinance backend via clean HTTP/REST endpoints.
- **Token-Based Authentication**: Uses bearer token authentication for secure, per-user/per-machine access.
- **Broker Abstraction**: Pluggable broker adapters allow easy switching between simulators and real brokers (miniQMT, etc.).
- **Closed-Loop Trading**: Fetches signals → executes → reports results → updates backend status.
- **Distributed Deployment**: Run independently on any machine with network access to backend (Windows, Linux, Mac).
- **Position Synchronization**: Real-time position sync from broker for full portfolio control.
- **Portfolio Management**: Track costs, P&L, risk metrics across all positions.
- **Strategy Suggestions**: AI-ready analysis and grid strategy generation on existing holdings.
- **Data Export**: Export position and trade data for AI/ML analysis.

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <quantTrader-repo-url> /path/to/quantTrader
cd /path/to/quantTrader

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package
pip install -e .
```

### 2. Obtain Access Token

Login to the quantFinance backend to get your access token:

```bash
# Example using curl (replace with actual backend URL and credentials)
curl -X POST http://<backend-host>:8000/api/user/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

Response will include:
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "user": { "id": "...", "username": "..." }
}
```

Copy the `access_token` value.

### 3. Create Configuration

Create a `config.json` file in your working directory (this file is **NOT tracked by Git** for security):

```json
{
  "api_base_url": "http://<backend-host>:8000/api",
  "api_token": "<your-access-token-here>",
  "poll_interval": 1.0,
  "log_level": "INFO"
}
```

**IMPORTANT**: Keep `config.json` out of version control. It contains your authentication token.

Alternatively, set environment variables:

```bash
export TRADER_API_BASE_URL="http://<backend-host>:8000/api"
export TRADER_API_TOKEN="<your-access-token-here>"
export TRADER_POLL_INTERVAL="1.0"
export TRADER_LOG_LEVEL="INFO"
```

### 4. Run quantTrader

```bash
# Using config file
python -m quant_trader.cli --config config.json

# Or using environment variables (if set)
python -m quant_trader.cli
```

You should see logs like:
```
2025-12-22 12:34:56 [INFO] quantTrader: quantTrader logging initialized
2025-12-22 12:34:56 [INFO] quantTrader: Log file: ~/.local/share/quantTrader/logs/quantTrader.log
2025-12-22 12:34:56 [INFO] quantTrader: Log level: INFO
2025-12-22 12:34:56 [INFO] quant_trader.trader_loop: quantTrader started. API=http://backend:8000/api
2025-12-22 12:34:56 [INFO] quant_trader.trader_loop: Position sync: ENABLED (interval=60s)
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Fetched 0 pending signals
2025-12-22 12:35:57 [INFO] quant_trader.trader_loop: Portfolio: 3 positions, Value=¥125,340.00, P&L=¥+2,450.00 (+2.0%)
```

### Log Files

quantTrader automatically writes logs to platform-appropriate directories:

**Linux/macOS:**
- `~/.local/share/quantTrader/logs/quantTrader.log`

**Windows:**
- `%LOCALAPPDATA%\quantTrader\logs\quantTrader.log`
- Typically: `C:\Users\<YourName>\AppData\Local\quantTrader\logs\quantTrader.log`

Log rotation:
- Maximum file size: 10MB
- Keeps 5 backup files (quantTrader.log.1, .2, etc.)
- Total log storage: ~50MB max

## Configuration

### Config File Format (`config.json`)

```json
{
  "api_base_url": "string (required) - Base URL of quantFinance backend",
  "api_token": "string (required) - Bearer token from /api/user/login",
  "poll_interval": "float (optional) - Seconds between signal polling, default: 1.0",
  "log_level": "string (optional) - Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL, default: INFO",
  "securities_account_id": "string (optional) - MongoDB _id from securities_accounts collection",
  "broker": "string (optional) - Broker type: simulated or miniQMT, default: simulated",
  "miniQMT": {
    "account_id": "string - miniQMT account ID",
    "session_path": "string - Path to miniQMT session files"
  }
}
```

#### Securities Account Linking

The `securities_account_id` field links your quantTrader instance to a configured broker account in the backend database:

**Purpose:**
- Associates real-time position/account data with specific broker configuration
- Enables multi-account support (multiple traders, each linked to different broker accounts)
- Allows querying positions by broker and account_id
- Provides complete audit trail: config → credentials → real-time data

**How to get securities_account_id:**
1. Login to quantFinance dashboard
2. Navigate to Account Settings → Securities Accounts
3. Add your broker account (broker name, account ID, credentials)
4. Copy the account ID from the list
5. Add it to your quantTrader `config.json`:

```json
{
  "api_base_url": "http://backend:8000/api",
  "api_token": "eyJhbGc...",
  "securities_account_id": "6763f8a2d9e4b1a2c3d4e5f6",
  "broker": "miniQMT",
  "miniQMT": {
    "account_id": "55000001",
    "session_path": "/path/to/userdata_mini"
  }
}
```

**Database Schema:**
```
securities_accounts (static configuration)
├─ _id: ObjectId
├─ user_id: string
├─ broker: string (券商名称，如 "国金证券", "华泰证券")
├─ account_id: string (券商账号，如 "55000001")
├─ password_enc: string (加密后的密码)
└─ created_at: datetime

trader_accounts (real-time balance data)
├─ user_id: string
├─ securities_account_id: ObjectId (FK → securities_accounts._id)
├─ broker: string (自动从 securities_accounts 复制)
├─ account_id: string (自动从 securities_accounts 复制)
├─ total_asset: float
├─ cash: float
├─ available_cash: float
└─ synced_at: timestamp

trader_positions (real-time holdings)
├─ user_id: string
├─ securities_account_id: ObjectId (FK → securities_accounts._id)
├─ broker: string (自动从 securities_accounts 复制)
├─ account_id: string (自动从 securities_accounts 复制)
├─ symbol: string
├─ quantity: int
├─ avg_cost: float
└─ synced_at: timestamp
```

**Important Notes:**
- `broker` field stores the **broker company name** (券商名称), NOT the trading tool name
- Example valid broker names: "国金证券", "华泰证券", "中信证券"
- Example invalid: "miniQMT" (this is just a trading interface tool, not a broker)
- The `broker` field is automatically populated from `securities_accounts` table
- Multiple brokers can use the same trading tool (e.g., both 国金 and华泰 can use miniQMT)

**Benefits:**
- **Multi-Account Management**: Run multiple quantTrader instances, each linked to different broker accounts
- **Data Isolation**: Positions from different accounts are properly separated
- **Audit Trail**: Track which broker/account generated each trade
- **Broker Correlation**: Link real-time data back to static account configuration
- **Permission Control**: Future support for account-level access control

### Environment Variables

If no `--config` file is provided, quantTrader reads from environment:

- `TRADER_API_BASE_URL` - Base URL of backend API
- `TRADER_API_TOKEN` - Bearer token
- `TRADER_POLL_INTERVAL` - Poll interval in seconds (default: 1.0)
- `TRADER_LOG_LEVEL` - Logging level (default: INFO)
- `TRADER_SECURITIES_ACCOUNT_ID` - Securities account MongoDB _id (optional)
- `TRADER_BROKER` - Broker type: simulated or miniQMT (default: simulated)

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────┐
│                    quantTrader                          │
├─────────────────────────────────────────────────────────┤
│  CLI                                                    │
│  └─> Load config                                        │
│      └─> Initialize TraderApiClient (REST)              │
│      └─> Initialize BrokerAdapter (pluggable)           │
│      └─> Create TraderLoop                              │
│          └─> run_forever()                              │
│              ├─> Fetch signals from /api/trader/signals │
│              ├─> Place order via BrokerAdapter          │
│              ├─> Report execution to /api/trader/...    │
│              └─> Loop until stopped                     │
└─────────────────────────────────────────────────────────┘
```

### Key Classes

- **`TraderConfig`**: Dataclass holding all configuration.
- **`TraderApiClient`**: Thin REST client for backend trader APIs.
  - `get_pending_signals()` - Fetch executable signals for current user
  - `update_signal_status()` - Update signal status (submitted, failed, etc.)
  - `create_execution()` - Report execution results
- **`BrokerAdapter`** (abstract): Interface for broker implementations.
  - `place_order()` - Submit order and return broker order ID
  - `close()` - Cleanup
- **`SimulatedBroker`** (concrete): Simulates orders without touching real broker.
- **`TraderLoop`**: Main orchestration logic.
  - Polls signals
  - Delegates to broker
  - Reports results
  - Handles errors gracefully

## REST API Contract

### Backend Endpoints Used

All requests include header:
```
Authorization: Bearer <api_token>
Content-Type: application/json
```

#### GET /api/trader/signals

Fetch pending trade signals for the current user.

**Parameters:**
- `limit` (int, optional): Max signals to return (1-500, default: 50)
- `include_submitted` (bool, optional): Include "submitted" signals (default: false)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "order_id": "ORD-20241222-001",
      "user_id": "user123",
      "symbol": "000858.SZ",
      "action": "BUY",
      "size": 100,
      "price": 15.5,
      "strategy": "mean_reversion",
      "strategy_name": "Mean Reversion Strategy",
      "status": "pending",
      "is_executable": true,
      "mode": "live",
      "created_at": 1703256000.0,
      "securities_account_id": "SA-001",
      "account_id": "ACC-001",
      "broker": "qmt"
    }
  ],
  "count": 1
}
```

#### POST /api/trader/signals/{order_id}/status

Update the status of a pending signal.

**Body (all fields optional, only whitelisted ones applied):**
```json
{
  "status": "submitted|failed|retry_pending",
  "qmt_order_id": "QMT-12345",
  "retry_count": 1,
  "last_error": "Connection timeout",
  "submitted_at": 1703256060.0,
  "executed_at": 1703256120.0,
  "filled_qty": 100,
  "avg_price": 15.5
}
```

**Response:**
```json
{
  "success": true,
  "message": "Signal status updated"
}
```

#### POST /api/trader/executions

Record an execution result. Backend auto-enriches with `user_id`, `date`, `datetime`.

**Body:**
```json
{
  "order_id": "ORD-20241222-001",
  "symbol": "000858.SZ",
  "action": "BUY",
  "size": 100,
  "target_price": 15.5,
  "filled_price": 15.5,
  "filled_size": 100,
  "commission": 5.0,
  "status": "filled",
  "broker": "qmt",
  "qmt_order_id": "QMT-12345",
  "securities_account_id": "SA-001",
  "account_id": "ACC-001",
  "strategy": "mean_reversion",
  "strategy_name": "Mean Reversion Strategy",
  "mode": "live",
  "timestamp": 1703256120.0
}
```

**Response:**
```json
{
  "success": true,
  "message": "Execution recorded"
}
```

## Broker Adapters

### SimulatedBroker (Default)

Simulates order execution without touching any real trading system. Useful for testing and validation.

```python
from quant_trader.broker_simulated import SimulatedBroker

broker = SimulatedBroker()
```

### Creating a Custom Broker Adapter

Implement the `BrokerAdapter` interface:

```python
from quant_trader.broker_base import BrokerAdapter

class MyBroker(BrokerAdapter):
    def place_order(self, signal: Dict[str, Any]) -> str:
        """
        Place an order and return the broker's order ID.
        
        Args:
            signal: Trade signal dict with symbol, action, size, price, etc.
        
        Returns:
            Broker order ID (string)
        """
        # Your broker integration logic here
        broker_order_id = "..."
        return broker_order_id
    
    def close(self) -> None:
        """Clean up resources."""
        pass
```

Then use it in `cli.py`:

```python
from your_module import MyBroker

def main(argv=None):
    # ... config loading ...
    api = TraderApiClient(cfg)
    broker = MyBroker()  # <-- Use your broker
    loop = TraderLoop(cfg, api, broker)
    # ...
```

## Troubleshooting

### "Connection refused" when starting

## Position Management

### Overview

quantTrader includes comprehensive position management capabilities that enable:
1. **Real-time position synchronization** from broker accounts
2. **Portfolio monitoring** with P&L tracking
3. **Grid strategy suggestions** for cost reduction on existing holdings
4. **Risk analysis** across all positions
5. **Data export** for AI/ML analysis

### Position CLI Tools

```bash
# View all current positions
python -m quant_trader.position_cli --config config.json positions

# Show portfolio summary
python -m quant_trader.position_cli --config config.json summary

# Get grid strategy suggestion for reducing cost
python -m quant_trader.position_cli --config config.json grid 000858.SZ

# Analyze risk across portfolio
python -m quant_trader.position_cli --config config.json risk

# Export all data for AI analysis
python -m quant_trader.position_cli --config config.json export positions.json
```

### Example: View Positions

```bash
$ python -m quant_trader.position_cli --config config.json positions

====================================================================================================
Symbol           Qty    Avail      Cost      Price        Value          P&L      P&L%
====================================================================================================
000858.SZ       1000     1000    ¥42.50     ¥43.20    ¥43,200.00      ¥700.00    +1.65%
002050.SZ        500      500    ¥38.00     ¥37.50    ¥18,750.00     ¥-250.00    -1.32%
600519.SH        100      100   ¥1850.00   ¥1920.00   ¥192,000.00    ¥7,000.00    +3.78%
====================================================================================================
```

### Example: Portfolio Summary

```bash
$ python -m quant_trader.position_cli --config config.json summary

============================================================
PORTFOLIO SUMMARY
============================================================
Total Positions:  3
Total Value:      ¥253,950.00
Total Cost:       ¥246,500.00
Total P&L:        ¥+7,450.00
Total P&L %:      +3.02%
Last Sync:        2025-12-23T11:45:00
============================================================

Top Positions by Value:
------------------------------------------------------------
1. 600519.SH      Value=  ¥192,000.00 P&L=  +7000.00 ( +3.78%)
2. 000858.SZ      Value=   ¥43,200.00 P&L=   +700.00 ( +1.65%)
3. 002050.SZ      Value=   ¥18,750.00 P&L=   -250.00 ( -1.32%)
```

### Example: Grid Strategy Suggestion

```bash
$ python -m quant_trader.position_cli --config config.json grid 000858.SZ

================================================================================
GRID STRATEGY SUGGESTION FOR 000858.SZ
================================================================================

Current Position:
  Quantity:        1,000 shares
  Average Cost:    ¥42.50
  Current Price:   ¥43.20
  Unrealized P&L:  +1.65%

Suggested Grid Parameters:
  Number of Grids:     10
  Grid Spacing:        5.0%
  Buy Grid Size:       100 shares
  Sell Grid Size:      100 shares

Expected Outcome:
  Target Cost:         ¥40.38
  Cost Reduction:      5.0%
  Max Position:        1,500 shares
  Estimated Duration:  30 days

Description:
  Grid strategy to reduce cost from ¥42.50 to ¥40.38 by buying 100 shares
  on 5% dips and selling on rallies
================================================================================
```

### Example: Risk Analysis

```bash
$ python -m quant_trader.position_cli --config config.json risk

====================================================================================================
RISK ANALYSIS
====================================================================================================
Symbol       Concentration     Drawdown  Liquidity Risk  Risk Score
====================================================================================================
000858.SZ           17.01%       0.00%            0.00%         0/100
002050.SZ            7.38%       1.32%            0.00%        40/100
600519.SH           75.61%       0.00%            0.00%        30/100
====================================================================================================
```

**Risk Score Interpretation**:
- **0-30**: Low risk
- **31-60**: Medium risk (consider rebalancing)
- **61-100**: High risk (immediate action needed)

### Strategic Use Cases

#### 1. Cost Reduction on Losing Positions

```python
# Get suggestion for underwater position
python -m quant_trader.position_cli --config config.json grid 002050.SZ

# Implement suggested grid strategy in quantFinance backend
# This will:
# - Buy more shares on dips (DCA)
# - Sell partial positions on rallies
# - Gradually reduce average cost
```

#### 2. AI-Powered Portfolio Analysis

```bash
# Export all position data
python -m quant_trader.position_cli --config config.json export portfolio_data.json

# Feed to AI model for:
# - Risk pattern recognition
# - Optimal strategy selection
# - Entry/exit timing suggestions
# - Portfolio rebalancing recommendations
```

#### 3. Real-time Monitoring Integration

The position manager automatically syncs every 60 seconds when running the main trader:

```bash
python -m quant_trader.cli --config config.json

# Logs will show:
# [INFO] Portfolio: 3 positions, Value=¥253,950.00, P&L=¥+7,450.00 (+3.02%)
```

### Integration with Strategies

**Scenario**: You hold 1000 shares of 000858.SZ at ¥42.50 cost, current price ¥40.00 (-5.9%)

**Without Position Sync**: Worker generates buy/sell signals with no awareness of existing position

**With Position Sync**:
1. Position manager detects underwater position
2. Suggests 10-level grid strategy (5% spacing)
3. Worker can execute grid strategy ON TOP of existing position
4. Grid buys at ¥38.00, ¥36.10, ¥34.30... (dollar-cost averaging)
5. Grid sells at ¥42.00, ¥44.10, ¥46.30... (profit taking)
6. Result: Average cost reduced from ¥42.50 to ¥40.38 over 30 days

## Troubleshooting

### "Connection refused" when starting

- **Check**: Is the quantFinance backend running and reachable at `api_base_url`?
- **Check**: Firewall rules allowing outbound connections.
- **Check**: `api_base_url` format: should be `http://host:port/api` (no trailing slash).

### "401 Unauthorized" or "403 Forbidden"

- **Check**: Is `api_token` correct and not expired?
- **Check**: Has the token been revoked on the backend?
- **Action**: Re-login to get a fresh token via `POST /api/user/login`.

### No signals being fetched

- **Check**: Are there pending signals in the backend for your `user_id`?
- **Check**: Are signals marked as `is_executable = true` and `mode = "live"`?
- **Check**: Logs should show "Fetched 0 pending signals" if none exist (not an error).

### Execution reports not appearing in backend

- **Check**: Are you seeing "Reported execution for order_id=..." in logs?
- **Check**: Backend `/api/trader/executions` endpoint is working (test with curl).
- **Check**: Check backend logs for any insertion errors.

### Cannot find log files

- **Linux/macOS**: Logs are in `~/.local/share/quantTrader/logs/`
- **Windows**: Logs are in `%LOCALAPPDATA%\quantTrader\logs\`
- **Check**: Run `python -m quant_trader.cli --config config.json` and look for "Log file:" in console output
- **Manual check**: The log directory is created automatically on first run

## Security Notes

- **Never commit `config.json`** with real tokens. Use `.gitignore`.
- **Tokens should be rotated regularly** on the backend.
- **Use environment variables** instead of config files in CI/CD or shared machines.
- **Keep quantTrader running in a secure, controlled environment**.
- If deploying to production, consider:
  - Using Windows Credential Manager (Windows) to store tokens securely.
  - Implementing built-in token refresh (not yet implemented).
  - Running as a service with proper permissions.

## Development

### Project Structure

```
quantTrader/
├── .gitignore                      # Ignore config files with secrets
├── README.md                       # This file
├── pyproject.toml                  # Build configuration
├── src/quant_trader/
│   ├── __init__.py
│   ├── cli.py                      # CLI entry point
│   ├── config.py                   # Configuration loading
│   ├── api_client.py               # REST client
│   ├── broker_base.py              # Abstract broker interface
│   ├── broker_simulated.py         # Simulated broker implementation
│   └── trader_loop.py              # Main trading loop
└── tests/                          # (Future) Unit & integration tests
```

### Running Tests

```bash
# (Tests not yet implemented; contributions welcome!)
```

### Code Style

- Python 3.9+
- Type hints recommended
- Follow PEP 8 conventions

## Future Enhancements

- [ ] Token refresh mechanism
- [ ] Real miniQMT broker adapter
- [ ] WebSocket support for real-time signals (vs polling)
- [ ] Windows service integration
- [ ] Secure token storage (Windows Credential Manager)
- [ ] Unit & integration tests
- [ ] Prometheus metrics export
- [ ] Performance optimization for high-frequency signals

## License

[Same as parent quantFinance project]

## Support

For issues or questions:
1. Check the **Troubleshooting** section above.
2. Review backend logs at `/api/trader/signals` (test with curl).
3. Enable `log_level: "DEBUG"` in config for detailed output.
4. Consult the quantFinance backend documentation.
