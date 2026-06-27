from __future__ import annotations

import os

if os.getenv("QUANT_TRADER_ENV") != "dev":
    raise RuntimeError("fake xtquant is development/test only; set QUANT_TRADER_ENV=dev to use it")

from . import xtconstant, xttrader, xttype

__all__ = ["xtconstant", "xttrader", "xttype"]
