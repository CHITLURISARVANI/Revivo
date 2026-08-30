"""Pytest fixtures for Revivo tests — isolated temp DB per session."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets a fresh SQLite DB."""
    db_path = tmp_path / "test_Revivo.db"
    monkeypatch.setenv("Revivo_DB_PATH", str(db_path))
    # Clear any cached modules that might hold old path — force re-init
    from core.database import init_db, reset_db
    reset_db()
    yield
    # cleanup handled by tmp_path


@pytest.fixture
def boundaries_config(tmp_path, monkeypatch):
    """Writable boundaries.json for tests."""
    import json
    from core import boundary_enforcer

    config = {
        "merchant": {"name": "Test Merchant"},
        "capture_guardian": {
            "enabled": True,
            "auto_capture_threshold_inr": 50000,
            "min_authorized_age_hours": 6,
            "escalate_above_threshold": True,
        },
        "retry_strategist": {
            "enabled": True,
            "max_retries_per_payment": 2,
            "retry_delay_minutes": 30,
            "retry_only_above_inr": 100,
            "classify_with_ai": True,
        },
        "dispute_defender": {
            "enabled": True,
            "auto_contest_threshold_inr": 25000,
            "never_auto_contest_categories": ["fraud"],
            "min_winnability_score": 0.6,
            "escalate_above_threshold": True,
        },
        "refund_resolver": {
            "enabled": True,
            "auto_reissue_threshold_inr": 10000,
            "min_pending_age_days": 7,
            "max_reissue_attempts": 1,
            "escalate_above_threshold": True,
        },
        "checkout_rescuer": {
            "enabled": True,
            "min_order_amount_inr": 500,
            "delay_before_recovery_minutes": 30,
            "max_recovery_messages_per_order": 1,
            "give_up_after_hours": 24,
        },
    }
    path = tmp_path / "boundaries.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(boundary_enforcer, "BOUNDARIES_PATH", str(path))
    return config


@pytest.fixture
def simulated_razorpay():
    """Razorpay client forced into simulated mode."""
    from razorpay_client.client import RazorpayClient
    return RazorpayClient(key_id=None, key_secret=None)
