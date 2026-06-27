"""Tests for quant_trader.config.load_config."""

from __future__ import annotations

import json

import pytest

from quant_trader.config import load_config


def test_load_config_db_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_BACKEND_MODE", "db")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("TRADER_USER_ID", "user-abc")
    monkeypatch.delenv("TRADER_API_BASE_URL", raising=False)
    monkeypatch.delenv("TRADER_API_TOKEN", raising=False)
    cfg = load_config(None)
    assert cfg.backend_mode == "db"
    assert cfg.mongo_uri == "mongodb://localhost:27017"
    assert cfg.user_id == "user-abc"
    assert cfg.api_base_url == ""


def test_load_config_db_missing_user_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_BACKEND_MODE", "db")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.delenv("TRADER_USER_ID", raising=False)
    monkeypatch.delenv("TRADER_API_BASE_URL", raising=False)
    monkeypatch.delenv("TRADER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="user_id is required"):
        load_config(None)


def test_load_config_api_requires_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_BACKEND_MODE", "api")
    monkeypatch.setenv("TRADER_API_BASE_URL", "http://localhost:8000/api")
    monkeypatch.delenv("TRADER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="api_token is required"):
        load_config(None)


def test_load_config_from_json_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADER_BACKEND_MODE", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("TRADER_USER_ID", raising=False)
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "backend_mode": "db",
                "mongo_uri": "mongodb://db:27017",
                "mongo_db": "finance",
                "user_id": "from-json",
                "poll_interval": 2.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.backend_mode == "db"
    assert cfg.user_id == "from-json"
    assert cfg.poll_interval == 2.0


def test_load_config_execution_json_and_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_BACKEND_MODE", "db")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("TRADER_USER_ID", "u1")
    monkeypatch.delenv("QUANT_TRADER_BUY_ORDER_TIMEOUT_SECONDS", raising=False)
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "backend_mode": "db",
                "mongo_uri": "mongodb://localhost:27017",
                "user_id": "u1",
                "execution": {
                    "buy_order_timeout_seconds": 120,
                    "cancel_retry_grace_seconds": 5,
                    "cancel_retry_interval_seconds": 10,
                    "trading_sessions": "CN_A",
                    "use_activate_after": True,
                    "sell_barrier_mode": "hard",
                    "sell_barrier_timeout_seconds": 30,
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.buy_order_timeout_seconds == 120
    assert cfg.cancel_retry_grace_seconds == 5
    assert cfg.cancel_retry_interval_seconds == 10
    assert cfg.trading_sessions == "CN_A"
    assert cfg.use_activate_after is True
    assert cfg.sell_barrier_mode == "hard"
    assert cfg.sell_barrier_timeout_seconds == 30

    monkeypatch.setenv("QUANT_TRADER_BUY_ORDER_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("QUANT_TRADER_TRADING_SESSIONS", "09:30-11:30")
    monkeypatch.setenv("QUANT_TRADER_SELL_BARRIER_MODE", "soft")
    monkeypatch.setenv("QUANT_TRADER_SELL_BARRIER_TIMEOUT_SECONDS", "60")
    cfg2 = load_config(str(p))
    assert cfg2.buy_order_timeout_seconds == 999
    assert cfg2.cancel_retry_grace_seconds == 5
    assert cfg2.trading_sessions == "09:30-11:30"
    assert cfg2.sell_barrier_mode == "soft"
    assert cfg2.sell_barrier_timeout_seconds == 60


def test_load_config_miniqmt_defaults_to_cn_a_session(tmp_path, monkeypatch):
    monkeypatch.delenv("QUANT_TRADER_TRADING_SESSIONS", raising=False)
    monkeypatch.delenv("QUANT_TRADER_USE_ACTIVATE_AFTER", raising=False)
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "backend_mode": "api",
                "api_base_url": "http://localhost:8000/api",
                "api_token": "token",
                "broker": "miniQMT",
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(p))

    assert cfg.trading_sessions == "CN_A"
    assert cfg.use_activate_after is True
    assert cfg.sell_barrier_mode == "off"
    assert cfg.sell_barrier_timeout_seconds == 0


def test_load_config_empty_trading_sessions_env_disables_session_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_TRADER_TRADING_SESSIONS", "")
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "backend_mode": "api",
                "api_base_url": "http://localhost:8000/api",
                "api_token": "token",
                "broker": "miniQMT",
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(p))

    assert cfg.trading_sessions == ""


def test_load_config_miniqmt_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADER_BACKEND_MODE", "db")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("TRADER_USER_ID", "u1")
    monkeypatch.setenv("TRADER_BROKER", "miniQMT")
    monkeypatch.setenv("TRADER_MINIQMT_XT_PATH", "/tmp/fake-userdata-mini")
    monkeypatch.setenv("TRADER_MINIQMT_ACCOUNT_ID", "SIM-ACC-0001")

    cfg = load_config(None)

    assert cfg.broker == "miniQMT"
    assert cfg.miniQMT == {
        "xt_path": "/tmp/fake-userdata-mini",
        "account_id": "SIM-ACC-0001",
    }
