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
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.buy_order_timeout_seconds == 120
    assert cfg.cancel_retry_grace_seconds == 5
    assert cfg.cancel_retry_interval_seconds == 10

    monkeypatch.setenv("QUANT_TRADER_BUY_ORDER_TIMEOUT_SECONDS", "999")
    cfg2 = load_config(str(p))
    assert cfg2.buy_order_timeout_seconds == 999
    assert cfg2.cancel_retry_grace_seconds == 5
