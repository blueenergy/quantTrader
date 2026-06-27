from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sim.matching_engine import EngineRegistry, SimMatchingEngine, default_engine, default_registry


def test_registry_lazy_creates_isolated_engines():
    registry = EngineRegistry()

    first = registry.get("ACC-1")
    second = registry.get("ACC-2")

    first.seed_position("000001.SZ", 100, 10.0)
    second.seed_position("000001.SZ", 200, 20.0)

    assert first is registry.get("ACC-1")
    assert second is registry.get("ACC-2")
    assert {pos.stock_code: pos.volume for pos in first.query_positions()} == {"000001.SZ": 100}
    assert {pos.stock_code: pos.volume for pos in second.query_positions()} == {"000001.SZ": 200}


def test_default_registry_keeps_default_engine_identity():
    default_registry.clear()
    default_engine.reset()
    default_registry.register(default_engine)

    assert default_registry.get(default_engine.account_id) is default_engine


def test_registry_reset_all_preserves_registered_engines():
    registry = EngineRegistry()
    engine = SimMatchingEngine(account_id="ACC-1")
    registry.register(engine)

    engine.seed_position("000001.SZ", 100, 10.0)
    registry.reset_all()

    assert registry.get("ACC-1") is engine
    assert engine.query_positions() == []
