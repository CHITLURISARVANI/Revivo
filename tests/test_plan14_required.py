"""
plan.md §14 — required test names (aliases + any missing cases).
Exact names requested for demo sign-off.
"""

import pytest
from core.boundary_enforcer import check_action
from core.audit_logger import log, get_audit_trail
from core.database import init_db, get_connection
from core.orchestrator import run_scan
from ai.classifier import classify_failure
from ai.winnability import score_dispute_winnability
from ai.message_gen import generate_recovery_message
from engines.retry_strategist import RetryStrategist
from engines.dispute_defender import DisputeDefender


# ─── Boundary ───

def test_capture_below_threshold_allowed(boundaries_config):
    result = check_action("capture_guardian", "auto_capture", 12000)
    assert result.allowed is True


def test_capture_above_threshold_escalated(boundaries_config):
    result = check_action("capture_guardian", "auto_capture", 65000)
    assert result.allowed is False
    assert result.escalate is True
    assert result.reason == "amount_exceeds_threshold"


def test_fraud_dispute_always_escalated(boundaries_config):
    result = check_action("dispute_defender", "auto_contest", 5000, category="fraud")
    assert result.allowed is False
    assert "category_restricted" in result.reason
    assert result.escalate is True


def test_max_retries_exceeded(boundaries_config):
    result = check_action("retry_strategist", "retry", 4500, retry_count=2)
    assert result.allowed is False
    assert result.reason == "max_retries_exceeded"


# ─── AI classifier / retry ───

def test_transient_failure_classified_correctly(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = classify_failure({
        "error_code": "UPI_S2S_DECLINED",
        "error_description": "declined by remitter bank",
        "payment_method": "upi",
        "amount": 4500,
    })
    assert result["classification"] == "transient"
    assert result["retry_recommended"] is True


def test_permanent_failure_not_retried(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    class FakeRP:
        def is_simulated(self):
            return True

        def fetch_failed_payments(self, hours=24):
            return [{
                "id": "pay_perm",
                "amount": 220000,
                "method": "card",
                "error_code": "INSUFFICIENT_FUNDS",
                "error_description": "Insufficient funds",
                "email": "a@b.com",
                "contact": "+9199",
                "description": "Order",
                "created_at": 1,
            }]

        def create_payment_link(self, **kwargs):
            raise AssertionError("must not create retry link for permanent failure")

    engine = RetryStrategist(
        FakeRP(),
        boundaries_config["retry_strategist"],
        "scan-perm",
    )
    result = engine.run()
    assert result["issues_found"] == 1
    assert result["issues"][0]["action_taken"] in ("no_retry", "blocked")
    assert result["issues"][0].get("ai_classification") == "permanent"


# ─── Audit ───

def test_audit_entry_is_append_only():
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("scan-append-only", "2026-08-30T00:00:00Z", "in_progress"),
    )
    conn.commit()
    conn.close()

    entry_id = log(
        scan_run_id="scan-append-only",
        engine="capture_guardian",
        phase="execute",
        human_readable="Captured payment pay_abc123 (₹12,000)",
    )
    conn = get_connection()
    with pytest.raises(Exception):
        conn.execute(
            "UPDATE audit_entries SET human_readable = ? WHERE id = ?",
            ("tampered", entry_id),
        )
        conn.commit()
    conn.close()
    trail = get_audit_trail("scan-append-only")
    assert trail[0]["human_readable"] == "Captured payment pay_abc123 (₹12,000)"


# ─── Orchestrator ───

def test_orchestrator_runs_all_enabled_engines(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    from scripts.seed_test_data import build_dataset, write_json

    write_json(build_dataset())
    result = run_scan()
    engines = {e["engine"] for e in result["engines"] if not e.get("skipped")}
    assert engines >= {
        "capture_guardian",
        "retry_strategist",
        "dispute_defender",
        "refund_resolver",
        "checkout_rescuer",
    }
    by_engine = {e["engine"]: e["issues_found"] for e in result["engines"] if not e.get("skipped")}
    assert by_engine["capture_guardian"] >= 1
    assert by_engine["retry_strategist"] >= 1
    assert by_engine["dispute_defender"] >= 1
    assert by_engine["refund_resolver"] >= 1
    assert by_engine["checkout_rescuer"] >= 1


def test_disabled_engine_skipped(boundaries_config, monkeypatch, tmp_path):
    import json
    from core import boundary_enforcer

    config = boundaries_config.copy()
    config["checkout_rescuer"] = {**config["checkout_rescuer"], "enabled": False}
    path = tmp_path / "boundaries.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(boundary_enforcer, "BOUNDARIES_PATH", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    result = run_scan()
    skipped = [e for e in result["engines"] if e.get("engine") == "checkout_rescuer"]
    assert skipped and skipped[0].get("skipped") is True


# ─── Dispute / message ───

def test_winnable_dispute_contested(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    class FakeRP:
        def is_simulated(self):
            return True

        def fetch_open_disputes(self):
            return [{
                "id": "disp_win",
                "amount": 820000,
                "payment_id": "pay_1",
                "reason_code": "product_not_received",
                "reason": "not received",
                "created_at": 1,
            }]

        def contest_dispute(self, dispute_id, evidence):
            return {"id": dispute_id, "status": "contested", "simulated": True}

    engine = DisputeDefender(FakeRP(), boundaries_config["dispute_defender"], "scan-win")
    result = engine.run()
    assert result["issues"][0]["action_taken"] == "contested"
    assert result["issues"][0]["ai_winnability_score"] >= 0.6


def test_low_winnability_escalated(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    score = score_dispute_winnability({
        "reason_code": "fraud",
        "available_evidence": {},
    })
    assert score["recommendation"] == "escalate"
    assert score["winnability_score"] < 0.6

    class FakeRP:
        def is_simulated(self):
            return True

        def fetch_open_disputes(self):
            return [{
                "id": "disp_fraud",
                "amount": 500000,
                "payment_id": "pay_2",
                "reason_code": "fraud",
                "reason": "fraud",
                "created_at": 1,
            }]

        def contest_dispute(self, *args, **kwargs):
            raise AssertionError("must not auto-contest fraud")

    engine = DisputeDefender(FakeRP(), boundaries_config["dispute_defender"], "scan-fraud")
    result = engine.run()
    assert result["issues"][0]["escalated"] is True
    assert result["issues"][0]["action_taken"] == "escalated"


def test_recovery_message_contains_payment_link(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    msg = generate_recovery_message(
        {"amount_inr": 7800, "items": "Headphones"},
        {"name": "Rahul"},
        "https://rzp.io/i/demo123",
    )
    assert "https://rzp.io/i/demo123" in msg["message"]
