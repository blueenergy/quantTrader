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


@pytest.mark.e2e
def test_miniqmt_simulated_sell_reduces_position_and_adds_cash(e2e_context, seed_signal):
    e2e_context.engine.seed_position("000005.SZ", volume=200, price=10.0)
    signal = seed_signal(order_id="SIM-SELL-HAPPY", symbol="000005.SZ", action="sell", size=100, price=10.0)

    e2e_context.loop.run_iteration()
    e2e_context.engine.tick()
    e2e_context.loop.run_iteration()

    filled_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert filled_signal["status"] == "filled"
    assert filled_signal["filled_qty"] == 100
    assert filled_signal["avg_price"] == 9.9

    position = e2e_context.db.trader_positions.find_one(
        {"user_id": SIM_USER_ID, "symbol": "000005.SZ", "account_id": SIM_ACCOUNT_ID}
    )
    assert position is not None
    assert position["qty"] == 100
    assert position["can_use_volume"] == 100

    account = e2e_context.db.trader_accounts.find_one(
        {"user_id": SIM_USER_ID, "account_id": SIM_ACCOUNT_ID}
    )
    assert account is not None
    assert account["cash"] == 1000990.0


@pytest.mark.e2e
def test_miniqmt_simulated_rejects_sell_when_position_insufficient(e2e_context, seed_signal):
    e2e_context.engine.seed_position("000006.SZ", volume=50, price=10.0)
    signal = seed_signal(order_id="SIM-SELL-INSUFFICIENT", symbol="000006.SZ", action="sell", size=100, price=10.0)

    e2e_context.loop.run_iteration()

    rejected_signal = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert rejected_signal["status"] == "rejected"
    assert "insufficient_available_position" in rejected_signal["last_error"]
    assert e2e_context.db.trade_executions.count_documents({"order_id": signal["order_id"], "user_id": SIM_USER_ID}) == 0
    assert e2e_context.engine.orders == {}


@pytest.mark.e2e
def test_miniqmt_simulated_buy_timeout_cancel_minus_one_missing_order(e2e_context, seed_signal):
    e2e_context.engine.set_next_order_scenario("remain_submitted")
    e2e_context.engine.set_next_cancel_mode("minus_one_remove_order")
    if e2e_context.loop.execution_tracker:
        e2e_context.loop.execution_tracker.buy_order_timeout_seconds = 0.0
    signal = seed_signal(
        order_id="SIM-BUY-TIMEOUT-CANCEL",
        symbol="000007.SZ",
        action="buy",
        size=100,
        price=10.0,
    )

    e2e_context.loop.run_iteration()

    cancel_requested = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert cancel_requested["status"] == "cancel_requested"
    assert cancel_requested["filled_qty"] == 0
    assert cancel_requested["remaining_size"] == 100

    e2e_context.loop.run_iteration()

    cancelled = e2e_context.db.trade_signals.find_one({"order_id": signal["order_id"], "user_id": SIM_USER_ID})
    assert cancelled["status"] == "cancelled"
    assert cancelled["last_error"] == "order_absent_from_broker_query_after_cancel"

    execution = e2e_context.db.trade_executions.find_one(
        {"order_id": signal["order_id"], "status": "cancelled", "user_id": SIM_USER_ID}
    )
    assert execution is not None
    assert execution["filled_size"] == 0
