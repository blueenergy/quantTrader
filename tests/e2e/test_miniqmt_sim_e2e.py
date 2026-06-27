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


@pytest.mark.e2e
def test_miniqmt_simulated_partial_then_fill(e2e_context, seed_signal):
    e2e_context.engine.set_next_order_scenario("partial_then_fill")
    signal = seed_signal(order_id="SIM-BUY-PARTIAL", symbol="000002.SZ", action="buy", size=100, price=20.0)

    e2e_context.loop.run_iteration()
    e2e_context.engine.tick()
    e2e_context.loop.run_iteration()

    partial_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert partial_signal["status"] == "partial_filled"
    assert partial_signal["filled_qty"] == 50
    assert partial_signal["avg_price"] == 20.0

    partial_execution = e2e_context.db.trade_executions.find_one(
        {"order_id": signal["order_id"], "status": "partial_filled", "user_id": SIM_USER_ID}
    )
    assert partial_execution is not None
    assert partial_execution["filled_size"] == 50
    assert partial_execution["sim_scenario"] == "partial_then_fill"

    e2e_context.engine.tick()
    e2e_context.loop.run_iteration()

    filled_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert filled_signal["status"] == "filled"
    assert filled_signal["filled_qty"] == 100

    filled_execution = e2e_context.db.trade_executions.find_one(
        {"order_id": signal["order_id"], "status": "filled", "user_id": SIM_USER_ID}
    )
    assert filled_execution is not None
    assert filled_execution["filled_size"] == 100


@pytest.mark.e2e
def test_miniqmt_simulated_rejects_junk_order(e2e_context, seed_signal):
    e2e_context.engine.set_next_order_scenario("reject_next_order")
    signal = seed_signal(order_id="SIM-BUY-REJECT", symbol="000003.SZ", action="buy", size=100, price=30.0)

    e2e_context.loop.run_iteration()

    rejected_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert rejected_signal["status"] == "rejected"
    assert rejected_signal["filled_qty"] == 0

    execution = e2e_context.db.trade_executions.find_one(
        {"order_id": signal["order_id"], "status": "rejected", "user_id": SIM_USER_ID}
    )
    assert execution is not None
    assert execution["filled_size"] == 0
    assert execution["simulated"] is True
    assert execution["sim_scenario"] == "reject_next_order"


@pytest.mark.e2e
def test_miniqmt_simulated_disconnect_does_not_reconcile_to_cancelled(e2e_context, seed_signal):
    signal = seed_signal(order_id="SIM-BUY-DISCONNECT", symbol="000004.SZ", action="buy", size=100, price=40.0)

    e2e_context.loop.run_iteration()
    submitted = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert submitted["status"] == "submitted"

    e2e_context.engine.fail_next_query_orders("none")
    e2e_context.loop.run_iteration()

    still_submitted = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert still_submitted["status"] == "submitted"
    assert still_submitted.get("last_error") != "submitted_entrust_absent_from_broker_query"

    e2e_context.engine.tick()
    e2e_context.loop.run_iteration()

    filled_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert filled_signal["status"] == "filled"
    assert filled_signal["filled_qty"] == 100
