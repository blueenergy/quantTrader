# quantTrader Known Limitations

This file tracks known limitations that we have consciously decided to
defer. Each entry records the symptom, the root cause, the options we
considered, and the current handling.

## 1. Account "daily P&L" (当日盈亏) is not available

### Status

Known limitation, **not implemented**. The misleading UI card has been
removed (see "Current handling" below).

### Symptom

The account dashboard ("账户工作台 / 账户概览") always showed a daily P&L
of `0`, regardless of how the market or the positions moved.

### Root cause

miniQMT does not expose a daily P&L on the account asset object.

`query_stock_asset()` returns an `XtAsset` that only contains balance
fields (`total_asset`, `cash`, `frozen_cash`, `market_value`,
`account_type`, `account_id`). There is **no** `pnl` / `pnl_ratio`
field.

The broker layer reads it defensively:

```python
# quantTrader/src/quant_trader/broker_miniQMT.py
"pnl": float(getattr(asset, 'pnl', 0)),
"pnl_ratio": float(getattr(asset, 'pnl_ratio', 0)),
```

Because the attribute does not exist, `getattr(..., 0)` always returns
the `0` fallback. That `0` is then synced into `trader_accounts` and
mapped to `daily_pnl` in `quantFinance/routers/trader.py::get_account`,
so the frontend can only ever display `0`.

The observation-mode path in the dashboard also hardcodes
`daily_pnl: 0` ("观察模式不计算日盈亏"), so neither path can produce a
non-zero value.

### Options considered (all deferred)

- **Option A — snapshot diff (simple)**
  `daily_pnl = total_asset_today - total_asset_prev_close`, using the
  previous trading day's last `trader_accounts` snapshot.
  Problem: this cannot tell apart real P&L from external cash transfers
  (出入金), and miniQMT has **no API to query intraday deposits /
  withdrawals**, so the number is contaminated on any transfer day.

- **Route 1 — snapshot diff + trade reconciliation**
  Infer the external cash flow as a residual:
  `external_flow = (cash_today - cash_prev) - net_trade_cash_flow`,
  where `net_trade_cash_flow = Σ sells - Σ buys - Σ fees` from
  `trade_executions` (fees are now recorded by quantTrader). Then
  `daily_pnl = Δtotal_asset - external_flow`.
  Problem: depends on complete and fee-accurate trade records; any
  mismatch with the broker's fee accounting leaves a residual that
  shows up as noise.

- **Option B — position-based (correct, heavier)**
  `daily_pnl = Σ(price_now - prev_close) × overnight_volume`
  `         + intraday unrealized on positions opened today`
  `         + realized P&L on positions closed today`.
  Immune to 出入金 (cash transfers do not change position market value),
  but requires per-symbol previous-close market data and splitting
  intraday open/close, which is meaningfully more work.

### Why deferred

The accurate options require either market data plumbing (Option B) or
fee-accurate trade reconciliation (Route 1). The metric is not critical
for current workflows, so we are not paying that cost yet.

### Current handling

- The "当日盈亏" card was removed from the account dashboard
  (`quantFinance-dashboard/src/components/SecuritiesAccountDashboard.vue`)
  to avoid showing a permanently-zero, misleading number.
- The `pnl` / `pnl_ratio` fields are still synced and returned by the
  API (they are harmless and may be reused if a real source appears).

### If we revisit

Prefer **Option B** when daily P&L accuracy matters, since it sidesteps
the 出入金 detection problem entirely. Otherwise **Route 1** is the most
accurate version achievable within the snapshot-diff approach.
