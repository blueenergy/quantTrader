# quantTrader Simulation E2E

This directory contains development-only simulation helpers for exercising the
real `MiniQMTBroker` path on Linux CI without Windows, miniQMT, or xtquant.

The simulator does **not** replace quantTrader. It replaces only the external
`xtquant` boundary used by `MiniQMTBroker`, so the tested path still flows
through the production broker adapter, `TraderLoop`, `ExecutionTracker`, and
`MongoTraderClient`.

## Test Tiers

### Tier A: CI Gate With Fake Mongo

Tier A is the fast PR/push gate.

- Database: `mongomock`
- Broker boundary: fake `xtquant`
- Trigger: every push / pull request
- CI behavior: Python 3.12 runs `tests/e2e`; Python 3.9 runs unit tests only

Run locally:

```bash
PYTHONPATH="src" python -m pytest -q tests/e2e -m e2e
```

### Tier B: System E2E With Real Mongo

Tier B uses the same e2e tests but points `MongoTraderClient` at a real MongoDB
service. This catches differences that `mongomock` may hide, such as real
`ObjectId`, upsert, query, and connection behavior.

- Database: real MongoDB
- Broker boundary: fake `xtquant`
- Trigger: `workflow_dispatch` and nightly schedule
- Nightly schedule: every day at `20:00 UTC`
- GitHub Actions job: `System e2e with MongoDB`

Run locally with your own MongoDB:

```bash
E2E_DB_BACKEND=real \
E2E_MONGO_URI="mongodb://127.0.0.1:27017" \
E2E_MONGO_DB="finance_e2e_local" \
PYTHONPATH="src" \
python -m pytest -q tests/e2e -m e2e
```

The real-Mongo fixture drops the configured e2e database at teardown. Use a
dedicated database name; never point `E2E_MONGO_DB` at production data.

## Simulation Markers

Simulation data is intentionally visible to humans:

- `user_id`: `sim-e2e-user`
- `account_id`: `SIM-ACC-0001`
- `broker`: `SIMULATED_MINIQMT`
- `trade_executions.simulated`: `true`
- `trader_accounts.simulated`: `true`
- `trade_executions.sim_scenario`: scenario name when applicable

Tests should not depend on these markers for lifecycle correctness. They are
for debugging and for making simulated rows easy to identify in MongoDB.

## Scenarios

`SimMatchingEngine` is deterministic. Tests drive it explicitly with `tick()`;
there are no background threads, random prices, or real-time sleeps.

Order scenarios:

- `fill_all_next_tick`: default; fills the full order on the next `tick()`.
- `partial_then_fill`: first `tick()` creates a partial fill, second `tick()`
  fills the remainder.
- `reject_next_order`: immediately returns a QMT junk order (`ORDER_JUNK`) so
  the broker maps it to `rejected`.
- `remain_submitted`: remains reported/submitted across ticks, useful for
  timeout and cancel tests.

Cancel scenarios:

- `minus_one_remove_order`: `cancel_order_stock` returns `-1` and removes the
  entrust from subsequent `query_stock_orders()` snapshots. This validates
  idempotent cancel handling for orders that disappear from QMT's live list.

Fault injection:

- `fail_next_query_orders("none")`: returns `None`, which must be treated as an
  untrusted broker snapshot.
- `fail_next_query_orders("exception")`: raises an exception, also treated as an
  untrusted snapshot.

Both fault modes should result in `BrokerQueryError` and must not reconcile a
live submitted order to `cancelled`.

## Extending Coverage

Prefer adding new deterministic scenarios to `SimMatchingEngine` and then
covering them in `tests/e2e/test_miniqmt_sim_e2e.py`.

Keep the simulator small:

- Simulate xtquant API semantics, not the miniQMT UI.
- Keep scenario state explicit and driven by tests.
- Do not change upstream/downstream Mongo contracts for simulation-only needs.
- Add fields only as optional debug markers.
