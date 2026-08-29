"""Capture Guardian engine tests."""

from engines.capture_guardian import CaptureGuardian


class FakeRazorpay:
    def __init__(self, payments):
        self._payments = payments

    def fetch_authorized_payments(self):
        return self._payments

    def capture_payment(self, payment_id, amount_inr):
        return {"id": payment_id, "status": "captured", "simulated": True}


def test_detects_authorized_payment_older_than_6h(boundaries_config):
    # created_at far in the past
    rp = FakeRazorpay([{
        "id": "pay_old",
        "amount": 1200000,
        "created_at": 1600000000,
        "method": "upi",
        "email": "a@b.com",
    }])
    engine = CaptureGuardian(rp, boundaries_config["capture_guardian"], "scan-cg-1")
    issues = engine.scan()
    assert len(issues) == 1
    assert issues[0]["payment_id"] == "pay_old"


def test_ignores_recent_authorized_payments(boundaries_config):
    import time
    rp = FakeRazorpay([{
        "id": "pay_new",
        "amount": 1200000,
        "created_at": int(time.time()) - 60,  # 1 minute ago
        "method": "upi",
    }])
    engine = CaptureGuardian(rp, boundaries_config["capture_guardian"], "scan-cg-2")
    issues = engine.scan()
    assert len(issues) == 0


def test_captures_below_threshold(boundaries_config):
    rp = FakeRazorpay([{
        "id": "pay_ok",
        "amount": 1200000,  # ₹12,000
        "created_at": 1600000000,
        "method": "upi",
    }])
    engine = CaptureGuardian(rp, boundaries_config["capture_guardian"], "scan-cg-3")
    result = engine.run()
    assert result["amount_recovered_inr"] == 12000
    assert result["escalated"] == 0


def test_escalates_above_threshold(boundaries_config):
    rp = FakeRazorpay([{
        "id": "pay_big",
        "amount": 6500000,  # ₹65,000
        "created_at": 1600000000,
        "method": "card",
    }])
    engine = CaptureGuardian(rp, boundaries_config["capture_guardian"], "scan-cg-4")
    result = engine.run()
    assert result["escalated"] == 1
    assert result["amount_recovered_inr"] == 0


def test_logs_audit_entry_on_capture(boundaries_config):
    from core.audit_logger import get_audit_trail
    from core.database import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("scan-cg-5", "2025-01-01T00:00:00Z", "in_progress"),
    )
    conn.commit()
    conn.close()

    rp = FakeRazorpay([{
        "id": "pay_audit",
        "amount": 500000,
        "created_at": 1600000000,
        "method": "upi",
    }])
    engine = CaptureGuardian(rp, boundaries_config["capture_guardian"], "scan-cg-5")
    engine.run()
    trail = get_audit_trail("scan-cg-5")
    assert any(e["phase"] == "execute" for e in trail)
