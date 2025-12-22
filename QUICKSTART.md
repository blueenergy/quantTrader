# quantTrader Quick Start (5 minutes)

## TL;DR - Get Running Now

```bash
# 1. Get token
curl -X POST http://localhost:8000/api/user/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your_user", "password": "your_pass"}'
# Copy the access_token from response

# 2. Setup
cd /Users/shuyonglin/code/quantTrader
pip install -e .

# 3. Create config
cat > config.json << EOF
{
  "api_base_url": "http://localhost:8000/api",
  "api_token": "<paste-token-here>",
  "poll_interval": 1.0,
  "log_level": "DEBUG"
}
EOF

# 4. Insert test signal
export MONGO_USER_ID="<your-user-id-from-login>"
python insert_test_signal.py

# 5. Run
python -m quant_trader.cli --config config.json

# 6. In another terminal, check results
curl http://localhost:8000/api/trader/signals -H "Authorization: Bearer <token>"
```

That's it! You should see the test signal being processed.

---

## Document Guide

| Document | Purpose | Time |
|----------|---------|------|
| **QUICKSTART.md** (this) | Get running in 5 min | 5 min |
| **README.md** | Complete user guide | 15 min |
| **E2E_TEST_GUIDE.md** | Detailed testing steps | 20 min |
| **SETUP_SUMMARY.md** | Architecture overview | 10 min |
| **TESTING_CHECKLIST.md** | Track your progress | As you test |

---

## What's Included

```
✅ Core quantTrader package (src/quant_trader/)
   - REST API client
   - Pluggable broker adapters
   - Main trader loop
   - CLI interface

✅ Documentation
   - README (complete guide)
   - E2E_TEST_GUIDE (step-by-step testing)
   - SETUP_SUMMARY (architecture)
   - TESTING_CHECKLIST (progress tracker)

✅ Tools
   - insert_test_signal.py (create test data)
   - .env.example (env var template)
   - .gitignore (protect secrets)
```

---

## Core Features

- 🔐 **Token-based auth** - RESTful API with bearer tokens
- 🔄 **Closed-loop** - Fetch signals → Execute → Report results
- 🧩 **Pluggable brokers** - Easy to swap simulators for real brokers
- 📦 **Minimal** - Only 5 modules, ~1000 LOC total
- 🛡️ **Secure** - No hardcoded secrets, config.json Git-ignored

---

## Expected Output

When you run `python -m quant_trader.cli --config config.json`:

```
2025-12-22 12:34:56 [INFO] quant_trader.config: Loading config from config.json
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: quantTrader started. API=http://localhost:8000/api
2025-12-22 12:34:57 [DEBUG] quant_trader.api_client: GET http://localhost:8000/api/trader/signals
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Fetched 1 pending signals
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Handling signal order_id=TEST-E2E-1734876897000
2025-12-22 12:34:57 [INFO] quant_trader.broker_simulated: SIMULATED place_order order_id=TEST-E2E-1734876897000 BUY 000858.SZ @ 15.5 size=100
2025-12-22 12:34:57 [DEBUG] quant_trader.api_client: POST http://localhost:8000/api/trader/signals/TEST-E2E-1734876897000/status
2025-12-22 12:34:57 [INFO] quant_trader.trader_loop: Reported execution for order_id=TEST-E2E-1734876897000
2025-12-22 12:34:58 [INFO] quant_trader.trader_loop: Fetched 0 pending signals
```

✅ If you see this, the system is working!

---

## Troubleshooting

### "Connection refused"
- Is backend running? Check `http://localhost:8000`
- Is `.api_base_url` correct in config.json?

### "401 Unauthorized"
- Is token expired? Re-login via `/api/user/login`
- Is it in the right format? Should be `Bearer <token>` in header

### "No signals fetching"
- Did you run `insert_test_signal.py`?
- Is signal marked `is_executable: true`?
- Check MongoDB: `db.trade_signals.findOne()`

### Help
1. Check **TESTING_CHECKLIST.md** - Common Issues section
2. Check **E2E_TEST_GUIDE.md** - Troubleshooting section
3. Enable `log_level: "DEBUG"` in config.json for verbose output

---

## Next Steps

✅ **Phase 1**: Get this working (5-30 min)
- [ ] Run through the TL;DR above

✅ **Phase 2**: Understand architecture (15 min)
- [ ] Read README.md
- [ ] Read SETUP_SUMMARY.md

✅ **Phase 3**: Validate everything (20 min)
- [ ] Follow E2E_TEST_GUIDE.md steps 1-7
- [ ] Check frontend shows your trade

✅ **Phase 4**: Add real broker (when ready)
- [ ] Implement miniQMT `BrokerAdapter`
- [ ] Swap `SimulatedBroker` for it
- [ ] Test on Windows

---

## Architecture (Simple Version)

```
Your Windows PC
  ↓
quantTrader polls → Backend (/api/trader/signals)
  ↓
SimulatedBroker (or real broker) places order
  ↓
quantTrader reports → Backend (/api/trader/executions)
  ↓
Backend updates → MongoDB
  ↓
Frontend shows trade ✅
```

---

## Security Reminders

🔒 **Protect your token**
- Never commit `config.json` (it's in `.gitignore`)
- Never share your token with others
- Rotate tokens regularly on backend

---

## Files

| File | Purpose |
|------|---------|
| `src/quant_trader/` | Core package |
| `insert_test_signal.py` | Create test data |
| `config.json` | **Your token** (Git-ignored) |
| `.gitignore` | Protect `config.json` |
| `.env.example` | Template for env vars |
| `README.md` | Full documentation |
| `E2E_TEST_GUIDE.md` | Testing guide |
| `SETUP_SUMMARY.md` | Architecture |
| `TESTING_CHECKLIST.md` | Progress tracker |

---

## Ready? 🚀

1. Follow **TL;DR** section above (5 min)
2. Run quantTrader
3. Watch the magic happen!

**Questions?** See README.md or TESTING_CHECKLIST.md

---

*Created: 2025-12-22 | quantTrader v0.0.1*
