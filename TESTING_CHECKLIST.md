# quantTrader Testing Checklist

Use this to track your end-to-end testing progress.

## Phase 1: Setup & Configuration ✅
- [ ] Read README.md
- [ ] Read E2E_TEST_GUIDE.md  
- [ ] Install quantTrader: `pip install -e .`
- [ ] Create config.json with your token
- [ ] Verify .gitignore will protect config.json

## Phase 2: Get Access Token ✅
- [ ] Get user_id from backend login response:
  ```bash
  curl -X POST http://localhost:8000/api/user/login \
    -H "Content-Type: application/json" \
    -d '{"username": "your_username", "password": "your_password"}'
  ```
- [ ] Copy `access_token` from response
- [ ] Copy `user_id` from response
- [ ] Verify token works:
  ```bash
  curl -X GET http://localhost:8000/api/trader/signals \
    -H "Authorization: Bearer <TOKEN>"
  ```
  Expected: `{"success": true, "data": [], "count": 0}` (empty list is OK)

## Phase 3: Create Test Signal ⏳
- [ ] Set user_id env var:
  ```bash
  export MONGO_USER_ID="your_user_id_here"
  ```
- [ ] Insert test signal:
  ```bash
  python insert_test_signal.py
  ```
- [ ] Verify signal was inserted:
  ```bash
  mongo localhost:27017/quant_finance
  > db.trade_signals.findOne({status: "pending"})
  ```

## Phase 4: Run quantTrader ⏳
- [ ] Start quantTrader:
  ```bash
  python -m quant_trader.cli --config config.json
  ```
- [ ] Watch logs for:
  - ✅ "quantTrader started"
  - ✅ "Fetched 1 pending signals"
  - ✅ "SIMULATED place_order"
  - ✅ "Reported execution"

## Phase 5: Verify Backend Updates ⏳
- [ ] Check signal was updated:
  ```bash
  curl -X GET http://localhost:8000/api/trader/signals \
    -H "Authorization: Bearer <TOKEN>"
  ```
  Expected: Signal should have `status: "submitted"` and `qmt_order_id`

- [ ] Check execution was recorded:
  ```bash
  mongo localhost:27017/quant_finance
  > db.trade_executions.findOne({order_id: "TEST-E2E-*"})
  ```
  Expected: Document with `status: "filled"`, `filled_size`, `filled_price`

## Phase 6: Verify Frontend Display ⏳
- [ ] Open quantFinance dashboard
- [ ] Navigate to Trade Execution / Trade History page
- [ ] Look for your test trade with:
  - ✅ Correct symbol (e.g., 000858.SZ)
  - ✅ Correct action (BUY)
  - ✅ Correct size (100)
  - ✅ Correct strategy name
  - ✅ Status = "filled"
  - ✅ Timestamp recent

## Phase 7: Error Handling ⏳
- [ ] Test invalid token:
  - Modify config.json with bad token
  - Start quantTrader
  - Verify it shows 401/403 errors (expected)
  - Fix token and restart

- [ ] Test network failure:
  - Stop backend
  - Verify quantTrader shows connection error (expected)
  - Restart backend
  - Verify quantTrader recovers

- [ ] Test no pending signals:
  - Delete all test signals from MongoDB
  - Run quantTrader
  - Verify logs show "Fetched 0 pending signals" (not an error)

## Phase 8: Cleanup ⏳
- [ ] Remove test signal from MongoDB:
  ```bash
  mongo localhost:27017/quant_finance
  > db.trade_signals.deleteMany({status: "submitted"})
  > db.trade_executions.deleteMany({strategy: "test_strategy"})
  ```
- [ ] Verify signal is gone:
  ```bash
  curl -X GET http://localhost:8000/api/trader/signals \
    -H "Authorization: Bearer <TOKEN>"
  ```

## Final Status
- [ ] All checks passed ✅
- [ ] System is production-ready for testing

---

## Common Issues & Quick Fixes

### "401 Unauthorized" or "403 Forbidden"
→ Token is invalid or expired. Re-login and update config.json

### "Connection refused" at `api_base_url`
→ Backend not running. Check backend is up at `http://localhost:8000`

### No signals fetching
→ Check MongoDB has `trade_signals` with `status: "pending"` and `is_executable: true`

### Execution not appearing in backend
→ Check backend logs for `/api/trader/executions` errors
→ Check MongoDB connection from quantTrader logs

### Can't find user_id
→ Check login response: `curl http://localhost:8000/api/user/login` (POST)
→ Or query: `mongo` → `db.users.findOne({username: "your_username"})`

---

## Notes

- Keep `config.json` out of git (protected by `.gitignore`)
- Never share your `TRADER_API_TOKEN` with others
- For sharing with friends later, create separate tokens for each user
- Test signals use `strategy: "test_strategy"` - easy to identify in logs

---

**Status**: Awaiting your test run! 🚀
