# End-to-End Testing Guide for quantTrader

This guide walks you through testing the full flow: signal creation → trader execution → result reporting.

## Prerequisites

- quantFinance backend running at `http://localhost:8000` (or your backend host)
- MongoDB with `quant_finance` database accessible to backend
- quantTrader installed locally (see README.md)
- Your user account created in the backend

## Step 1: Get Your Access Token

### Option A: Using Frontend (Recommended)

1. Open quantFinance dashboard in browser: `http://<backend-host>:80` (or `:5173` if dev)
2. Login with your credentials
3. Open browser DevTools → Network tab
4. Look for any API call and check the `Authorization: Bearer <token>` header
5. Copy the token value (without "Bearer " prefix)

### Option B: Using curl

```bash
curl -X POST http://localhost:8000/api/user/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

Response example:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "507f1f77bcf86cd799439011",
    "username": "your_username"
  }
}
```

Copy the `access_token` value.

## Step 2: Create quantTrader Config

Create `config.json` in your quantTrader working directory:

```json
{
  "api_base_url": "http://localhost:8000/api",
  "api_token": "<your-access-token-from-step-1>",
  "poll_interval": 1.0,
  "log_level": "DEBUG"
}
```

**Never commit this file!** It's in `.gitignore` for security.

## Step 3: Verify Backend Endpoints are Available

Test that the trader API endpoints exist:

```bash
# Replace with your token and host
TOKEN="<your-token>"
BASE="http://localhost:8000/api"

# Test /api/trader/signals
curl -X GET "$BASE/trader/signals" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

# Expected: {"success": true, "data": [], "count": 0} (empty list is fine)
```

If you get 404, the endpoints may not be deployed. Check backend logs and ensure `quantFinance/routers/trade_execution.py` has been updated with the trader endpoints.

## Step 4: Create a Test Trade Signal

You have two options:

### Option A: Insert via MongoDB (For Testing)

Use this to manually insert a test signal into the database:

```bash
cd /Users/shuyonglin/code/quantTrader

# Create insert_test_signal.py script (see next section)
python insert_test_signal.py
```

Or manually via mongo shell:

```javascript
// Connect to MongoDB
mongo localhost:27017/quant_finance

db.trade_signals.insertOne({
  order_id: "TEST-E2E-001",
  user_id: "your_user_id_here",  // Get from login response
  symbol: "000858.SZ",
  action: "BUY",
  size: 100,
  price: 15.5,
  strategy: "test_strategy",
  strategy_name: "Test E2E Strategy",
  status: "pending",
  is_executable: true,
  mode: "live",
  broker: "simulated",
  securities_account_id: "SA-001",
  account_id: "ACC-001",
  created_at: new Date(),
  updated_at: new Date()
});

// Verify it was inserted
db.trade_signals.findOne({order_id: "TEST-E2E-001"});
```

### Option B: Trigger via Backend Worker (Recommended for Real Testing)

If you have a worker/strategy generating signals, trigger it to create a real signal for you. Then proceed to Step 5.

## Step 5: Start quantTrader

```bash
cd /path/to/quantTrader

# Activate venv if needed
source venv/bin/activate

# Start trading
python -m quant_trader.cli --config config.json
```

Expected output:
```
2025-12-22 12:34:56 [INFO] quant_trader.cli: quantTrader - minimal REST trader client
2025-12-22 12:34:57 [INFO] quant_trader.config: Loading config from config.json
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: quantTrader started. API=http://localhost:8000/api
2025-12-22 12:34:57 [DEBUG] quant_trader.api_client: GET http://localhost:8000/api/trader/signals
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Fetched 1 pending signals
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Handling signal order_id=TEST-E2E-001
2025-12-22 12:34:57 [INFO] quant_trader.broker_simulated: SIMULATED place_order order_id=TEST-E2E-001 BUY 000858.SZ @ 15.5 size=100
2025-12-22 12:34:57 [DEBUG] quant_trader.api_client: POST http://localhost:8000/api/trader/signals/TEST-E2E-001/status
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Reported execution for order_id=TEST-E2E-001
2025-12-22 12:34:58 [INFO] quant_trader.trader_loop: Fetched 0 pending signals
```

If successful, the signal should have been processed!

## Step 6: Verify Results in Backend

### Check signal was updated:

```bash
curl -X GET "http://localhost:8000/api/trader/signals?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

The `TEST-E2E-001` signal should now have:
- `status: "submitted"`
- `qmt_order_id: "SIM-<timestamp>"`

### Check execution was recorded:

```bash
curl -X GET "http://localhost:8000/api/trade-activities" \
  -H "Authorization: Bearer $TOKEN"
```

You should see a new execution entry for `TEST-E2E-001` with:
- `status: "filled"`
- `filled_size: 100`
- `filled_price: 15.5`
- `strategy: "test_strategy"`

### Check in MongoDB directly:

```javascript
mongo localhost:27017/quant_finance

// Check signal status
db.trade_signals.findOne({order_id: "TEST-E2E-001"});

// Check execution
db.trade_executions.findOne({order_id: "TEST-E2E-001"});
```

## Step 7: Test Error Handling

### Simulate API failure:

Stop the backend while quantTrader is running. You should see:
```
[ERROR] quant_trader.trader_loop: Error in main loop: ...
```

quantTrader should recover automatically when backend comes back online.

### Simulate invalid token:

Modify `config.json` to use a bad token, restart. You should see:
```
[ERROR] quant_trader.api_client: 401 Unauthorized
```

### Simulate missing signal:

Once all pending signals are processed, you should see:
```
[INFO] quant_trader.trader_loop: Fetched 0 pending signals
```

## Step 8: Check Frontend Display

Open quantFinance dashboard in browser:

1. Navigate to **Trade Execution** or **Trade History** page
2. You should see your `TEST-E2E-001` trade with:
   - Correct symbol (000858.SZ)
   - Correct action (BUY)
   - Size (100)
   - Strategy (Test E2E Strategy)
   - Status (filled)
   - Timestamp

## Cleanup

After testing, you can remove the test data:

```javascript
mongo localhost:27017/quant_finance

db.trade_signals.deleteOne({order_id: "TEST-E2E-001"});
db.trade_executions.deleteOne({order_id: "TEST-E2E-001"});
```

## Troubleshooting

### quantTrader starts but doesn't fetch signals

1. **Check endpoint availability**:
   ```bash
   curl http://localhost:8000/api/trader/signals
   ```
   Should return 401 if no token, not 404.

2. **Check token**:
   ```bash
   curl -X GET http://localhost:8000/api/trader/signals \
     -H "Authorization: Bearer $TOKEN"
   ```
   If 403, token is invalid or expired.

3. **Check signal exists and is executable**:
   ```javascript
   db.trade_signals.findOne({order_id: "TEST-E2E-001"});
   ```
   Must have `is_executable: true` and `status: "pending"`.

### Signal not updating on backend

1. **Check quantTrader logs** for update failures (look for 404/403 errors)
2. **Verify token** by testing update manually:
   ```bash
   curl -X POST "http://localhost:8000/api/trader/signals/TEST-E2E-001/status" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"status": "submitted", "qmt_order_id": "TEST-123"}'
   ```

### Execution not recorded

1. **Check backend logs** for `/api/trader/executions` errors
2. **Verify MongoDB** connection and permissions
3. **Check schema**: ensure `timestamp` is numeric (Unix timestamp), not string

## Next Steps

Once e2e testing passes:

1. **Test with real broker adapter**: Implement miniQMT `BrokerAdapter` and swap `SimulatedBroker`
2. **Deploy to Windows**: Follow deployment guide (to be created)
3. **Add monitoring**: Implement health checks and logging
4. **Token refresh**: Implement automatic token refresh for long-running traders
