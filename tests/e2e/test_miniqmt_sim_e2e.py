from __future__ import annotations

import pytest

SIM_USER_ID = "sim-e2e-user"
SIM_ACCOUNT_ID = "SIM-ACC-0001"


@pytest.mark.e2e
def test_miniqmt_simulated_buy_happy_path(e2e_context, seed_signal):
    signal = seed_signal(order_id="SIM-BUY-HAPPY", symbol="000001.SZ", action="buy", size=100, price=10.0)

    e2e_context.loop.run_iteration()

    submitted = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert submitted["status"] == "submitted"
    assert submitted["qmt_order_id"]

    e2e_context.engine.tick()
    e2e_context.loop.run_iteration()

    filled_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert filled_signal["status"] == "filled"
    assert filled_signal["filled_qty"] == 100
    assert filled_signal["avg_price"] == 10.0

    execution = e2e_context.db.trade_executions.find_one(
        {"order_id": signal["order_id"], "status": "filled", "user_id": SIM_USER_ID}
    )
    assert execution is not None
    assert execution["filled_size"] == 100
    assert execution["filled_price"] == 10.0
    assert execution["simulated"] is True
    assert execution["sim_scenario"] == "fill_all_next_tick"

    position = e2e_context.db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "symbol": "000001.SZ", "account_id": SIM_ACCOUNT_ID}
    )
    assert position is not None
    assert position["qty"] == 100
    assert position["avg_price"] == 10.0

    account = e2e_context.db.trader_accounts.find_one(
        {"user_id": SIM_USER_ID, "account_id": SIM_ACCOUNT_ID}
    )
    assert account is not None
    assert account["simulated"] is True
    assert account["cash"] == 999000.0
