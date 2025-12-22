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
2025-12-22 12:34:56 [INFO] quant_trader.trader_loop: quantTrader started. API=http://backend:8000/api
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Fetched 0 pending signals
```

## Configuration

### Config File Format (`config.json`)

```json
{
  "api_base_url": "string (required) - Base URL of quantFinance backend",
  "api_token": "string (required) - Bearer token from /api/user/login",
  "poll_interval": "float (optional) - Seconds between signal polling, default: 1.0",
  "log_level": "string (optional) - Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL, default: INFO"
}
```

### Environment Variables

If no `--config` file is provided, quantTrader reads from environment:

- `TRADER_API_BASE_URL` - Base URL of backend API
- `TRADER_API_TOKEN` - Bearer token
- `TRADER_POLL_INTERVAL` - Poll interval in seconds (default: 1.0)
- `TRADER_LOG_LEVEL` - Logging level (default: INFO)

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
