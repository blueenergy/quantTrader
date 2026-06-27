from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, Optional


STOCK_BUY = 23
STOCK_SELL = 24
MARKET_PEER_PRICE_FIRST = 41
FIX_PRICE = 42

ORDER_REPORTED = 50
ORDER_JUNK = 51
ORDER_PART_SUCCEEDED = 52
ORDER_SUCCEEDED = 53
ORDER_PARTSUCC_CANCEL = 54
ORDER_CANCELED = 55
ORDER_WAIT_REPORTING = 56


@dataclass
class SimOrder:
    order_id: int
    stock_code: str
    order_type: int
    order_volume: int
    price_type: int
    price: float
    order_status: int = ORDER_REPORTED
    status_msg: str = "已报"
    traded_volume: int = 0
    traded_price: float = 0.0
    order_time: int = 0
    scenario: str = "fill_all_next_tick"
    ticks_seen: int = 0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    other_fee: float = 0.0


@dataclass
class SimPosition:
    stock_code: str
    volume: int
    can_use_volume: int
    frozen_volume: int
    open_price: float
    last_price: float

    @property
    def market_value(self) -> float:
        return float(self.volume) * float(self.last_price)


class SimMatchingEngine:
    """Small deterministic miniQMT-like matching engine for tests.

    The engine deliberately avoids background threads, random prices, and real
    time. Tests drive state transitions explicitly via ``tick()``.
    """

    def __init__(self, *, initial_cash: float = 1_000_000.0, account_id: str = "SIM-ACC-0001") -> None:
        self.initial_cash = float(initial_cash)
        self.account_id = account_id
        self.reset()

    def reset(self) -> None:
        self.cash = self.initial_cash
        self.frozen_cash = 0.0
        self.orders: Dict[int, SimOrder] = {}
        self.positions: Dict[str, SimPosition] = {}
        self.next_order_id = 1_000_001
        self.default_scenario = "fill_all_next_tick"
        self.next_order_scenario: Optional[str] = None
        self.next_query_orders_fault: Optional[str] = None

    def set_next_order_scenario(self, scenario: str) -> None:
        self.next_order_scenario = scenario

    def fail_next_query_orders(self, mode: str = "exception") -> None:
        if mode not in {"exception", "none"}:
            raise ValueError(f"Unsupported query fault mode: {mode}")
        self.next_query_orders_fault = mode

    def seed_position(self, stock_code: str, volume: int, price: float) -> None:
        self.positions[stock_code] = SimPosition(
            stock_code=stock_code,
            volume=int(volume),
            can_use_volume=int(volume),
            frozen_volume=0,
            open_price=float(price),
            last_price=float(price),
        )

    def place_order(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
    ) -> int:
        order_id = self.next_order_id
        self.next_order_id += 1
        scenario = self.next_order_scenario or self.default_scenario
        self.next_order_scenario = None
        order = SimOrder(
            order_id=order_id,
            stock_code=stock_code,
            order_type=int(order_type),
            order_volume=int(order_volume),
            price_type=int(price_type),
            price=float(price or self._last_price(stock_code)),
            scenario=scenario,
        )
        if scenario == "reject_next_order":
            order.order_status = ORDER_JUNK
            order.status_msg = "废单: simulated rejection"
        self.orders[order_id] = order
        return order_id

    def cancel_order(self, order_id: int) -> int:
        order = self.orders.get(int(order_id))
        if not order:
            return -1
        if order.order_status in {ORDER_SUCCEEDED, ORDER_CANCELED, ORDER_JUNK, ORDER_PARTSUCC_CANCEL}:
            return -1
        if order.traded_volume > 0:
            order.order_status = ORDER_PARTSUCC_CANCEL
            order.status_msg = "部撤"
        else:
            order.order_status = ORDER_CANCELED
            order.status_msg = "已撤"
        return 0

    def tick(self) -> None:
        for order in self.orders.values():
            if order.order_status in {ORDER_JUNK, ORDER_SUCCEEDED, ORDER_CANCELED, ORDER_PARTSUCC_CANCEL}:
                continue
            order.ticks_seen += 1
            if order.scenario == "partial_then_fill" and order.ticks_seen == 1:
                partial_qty = max(1, order.order_volume // 2)
                self._apply_fill(order, partial_qty)
                order.order_status = ORDER_PART_SUCCEEDED
                order.status_msg = "部成"
                continue
            self._apply_fill(order, order.order_volume - order.traded_volume)
            order.order_status = ORDER_SUCCEEDED
            order.status_msg = "已成"

    def query_orders(self):
        if self.next_query_orders_fault:
            mode = self.next_query_orders_fault
            self.next_query_orders_fault = None
            if mode == "none":
                return None
            raise RuntimeError("simulated miniQMT disconnect")
        return [self._order_namespace(order) for order in self.orders.values()]

    def query_positions(self):
        return [
            SimpleNamespace(
                stock_code=pos.stock_code,
                volume=pos.volume,
                can_use_volume=pos.can_use_volume,
                frozen_volume=pos.frozen_volume,
                open_price=pos.open_price,
                market_value=pos.market_value,
                last_price=pos.last_price,
                on_road_volume=0,
                yesterday_volume=pos.volume,
            )
            for pos in self.positions.values()
            if pos.volume > 0
        ]

    def query_asset(self):
        market_value = sum(pos.market_value for pos in self.positions.values())
        return SimpleNamespace(
            total_asset=self.cash + market_value,
            cash=self.cash,
            frozen_cash=self.frozen_cash,
            market_value=market_value,
            fetch_balance=self.cash,
            interest=0.0,
            asset_balance=self.cash + market_value,
            pnl=0.0,
            pnl_ratio=0.0,
            simulated=True,
        )

    def _apply_fill(self, order: SimOrder, quantity: int) -> None:
        quantity = max(0, int(quantity))
        if quantity <= 0:
            return
        fill_price = float(order.price or self._last_price(order.stock_code))
        order.traded_volume += quantity
        order.traded_price = fill_price
        order.commission = round(float(order.traded_volume) * fill_price * 0.0001, 4)
        if order.order_type == STOCK_BUY:
            self.cash -= fill_price * quantity
            self._increase_position(order.stock_code, quantity, fill_price)
        else:
            self.cash += fill_price * quantity
            self._decrease_position(order.stock_code, quantity)

    def _increase_position(self, stock_code: str, quantity: int, price: float) -> None:
        current = self.positions.get(stock_code)
        if not current:
            self.seed_position(stock_code, quantity, price)
            return
        total_qty = current.volume + quantity
        if total_qty <= 0:
            return
        current.open_price = ((current.open_price * current.volume) + (price * quantity)) / total_qty
        current.volume = total_qty
        current.can_use_volume = total_qty
        current.last_price = price

    def _decrease_position(self, stock_code: str, quantity: int) -> None:
        current = self.positions.get(stock_code)
        if not current:
            return
        current.volume = max(0, current.volume - quantity)
        current.can_use_volume = current.volume

    def _last_price(self, stock_code: str) -> float:
        position = self.positions.get(stock_code)
        return float(position.last_price) if position else 10.0

    @staticmethod
    def _order_namespace(order: SimOrder):
        return SimpleNamespace(
            order_id=order.order_id,
            stock_code=order.stock_code,
            order_type=order.order_type,
            order_status=order.order_status,
            status_msg=order.status_msg,
            order_volume=order.order_volume,
            price=order.price,
            traded_volume=order.traded_volume,
            traded_price=order.traded_price,
            order_time=order.order_time,
            commission=order.commission,
            stamp_tax=order.stamp_tax,
            transfer_fee=order.transfer_fee,
            other_fee=order.other_fee,
            simulated=True,
            sim_scenario=order.scenario,
        )


default_engine = SimMatchingEngine()
