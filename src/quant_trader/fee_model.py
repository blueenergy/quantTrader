from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class FeeBreakdown:
    commission: float
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    other_fee: float = 0.0
    estimated_fee: bool = True

    @property
    def total_fee(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee + self.other_fee

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commission": self.commission,
            "stamp_tax": self.stamp_tax,
            "transfer_fee": self.transfer_fee,
            "other_fee": self.other_fee,
            "total_fee": self.total_fee,
            "estimated_fee": self.estimated_fee,
        }


@dataclass(frozen=True)
class TradeFeeModel:
    buy_commission_rate: float = 0.0001
    sell_commission_rate: float = 0.0001
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.0

    @classmethod
    def from_config(cls, raw: Optional[Dict[str, Any]] = None) -> "TradeFeeModel":
        raw = raw or {}
        legacy_cost = _float_or_none(raw.get("transaction_cost"))
        return cls(
            buy_commission_rate=_coalesce_float(raw.get("buy_commission_rate"), legacy_cost, cls.buy_commission_rate),
            sell_commission_rate=_coalesce_float(raw.get("sell_commission_rate"), legacy_cost, cls.sell_commission_rate),
            min_commission=_coalesce_float(raw.get("min_commission"), cls.min_commission),
            stamp_tax_rate=_coalesce_float(raw.get("stamp_tax_rate"), 0.0 if legacy_cost is not None else cls.stamp_tax_rate),
            transfer_fee_rate=_coalesce_float(raw.get("transfer_fee_rate"), cls.transfer_fee_rate),
        )

    def estimate(self, action: str, amount: float) -> FeeBreakdown:
        side = str(action or "").lower()
        trade_amount = abs(float(amount or 0.0))
        rate = self.sell_commission_rate if side == "sell" else self.buy_commission_rate
        commission = max(trade_amount * rate, self.min_commission) if trade_amount > 0 else 0.0
        stamp_tax = trade_amount * self.stamp_tax_rate if side == "sell" else 0.0
        transfer_fee = trade_amount * self.transfer_fee_rate
        return FeeBreakdown(
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            estimated_fee=True,
        )

    def extract_or_estimate(self, action: str, amount: float, broker_status: Dict[str, Any]) -> FeeBreakdown:
        real_fee = _extract_real_fee(broker_status)
        if real_fee is not None:
            return real_fee
        return self.estimate(action, amount)


def _extract_real_fee(raw: Dict[str, Any]) -> Optional[FeeBreakdown]:
    commission = _first_number(raw, ("commission", "entrust_fee", "fee"))
    stamp_tax = _first_number(raw, ("stamp_tax", "stamp_duty", "tax"))
    transfer_fee = _first_number(raw, ("transfer_fee", "transfer_cost"))
    other_fee = _first_number(raw, ("other_fee", "other_cost", "handling_fee"))
    total_fee = _first_number(raw, ("total_fee", "fee_total", "cost", "total_cost"))

    explicit_parts = [value for value in (commission, stamp_tax, transfer_fee, other_fee) if value is not None]
    if explicit_parts:
        return FeeBreakdown(
            commission=float(commission or 0.0),
            stamp_tax=float(stamp_tax or 0.0),
            transfer_fee=float(transfer_fee or 0.0),
            other_fee=float(other_fee or 0.0),
            estimated_fee=False,
        )
    if total_fee is not None:
        return FeeBreakdown(commission=float(total_fee), estimated_fee=False)
    return None


def _first_number(raw: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = _float_or_none(raw.get(key))
        if value is not None:
            return value
    return None


def _coalesce_float(*values: Any) -> float:
    for value in values:
        number = _float_or_none(value)
        if number is not None:
            return number
    return 0.0


def _float_or_none(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None
