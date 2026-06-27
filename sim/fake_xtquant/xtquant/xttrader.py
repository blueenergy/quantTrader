from __future__ import annotations

import os

from sim.matching_engine import default_engine


def _auto_tick_enabled() -> bool:
    return os.getenv("QUANT_TRADER_SIM_AUTO_TICK", "").strip().lower() in {"1", "true", "yes", "on"}


class XtQuantTrader:
    def __init__(self, xt_path: str, session_id: int) -> None:
        self.xt_path = xt_path
        self.session_id = session_id
        self.started = False
        self.connected = False
        self.subscribed_account = None
        self.engine = default_engine

    def start(self):
        self.started = True
        return 0

    def connect(self):
        self.connected = True
        return 0

    def subscribe(self, account):
        self.subscribed_account = account
        self.engine.account_id = getattr(account, "account_id", self.engine.account_id)
        return 0

    def unsubscribe(self, account):
        if self.subscribed_account is account:
            self.subscribed_account = None
        return 0

    def stop(self):
        self.connected = False
        return 0

    def order_stock(self, account, stock_code, order_type, order_volume, price_type, price):
        return self.engine.place_order(
            stock_code=stock_code,
            order_type=order_type,
            order_volume=order_volume,
            price_type=price_type,
            price=price,
        )

    def query_stock_orders(self, account):
        if _auto_tick_enabled():
            self.engine.tick()
        return self.engine.query_orders()

    def query_stock_positions(self, account):
        return self.engine.query_positions()

    def query_stock_asset(self, account):
        return self.engine.query_asset()

    def cancel_order_stock(self, account, order_id):
        return self.engine.cancel_order(order_id)
