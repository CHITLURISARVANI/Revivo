"""Prove [SIMULATED] appears only when Razorpay response is simulated."""
from core.database import init_db, get_connection
from core.audit_logger import get_audit_trail
from engines.capture_guardian import CaptureGuardian


class LiveRP:
    def is_simulated(self):
        return False

    def fetch_authorized_payments(self):
        return []

    def capture_payment(self, pid, amt):
        return {"id": pid, "status": "captured", "simulated": False}


class SimRP:
    def is_simulated(self):
        return True

    def fetch_authorized_payments(self):
        return []

    def capture_payment(self, pid, amt):
        return {"id": pid, "status": "captured", "simulated": True}


def test_simulated_tag_only_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("Revivo_DB_PATH", str(tmp_path / "simtag.db"))
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("s-live", "2026-08-30", "in_progress"),
    )
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("s-sim", "2026-08-30", "in_progress"),
    )
    conn.commit()
    conn.close()

    cfg = {
        "enabled": True,
        "auto_capture_threshold_inr": 50000,
        "min_authorized_age_hours": 0,
    }
    issue = {"payment_id": "pay_x", "amount_inr": 12000, "age_hours": 14}
    diag = {"reason": "test"}

    CaptureGuardian(LiveRP(), cfg, "s-live").execute(issue, diag)
    CaptureGuardian(SimRP(), cfg, "s-sim").execute(issue, diag)

    live_txt = " ".join(
        e["human_readable"] for e in get_audit_trail("s-live") if e["phase"] == "execute"
    )
    sim_txt = " ".join(
        e["human_readable"] for e in get_audit_trail("s-sim") if e["phase"] == "execute"
    )

    assert "[SIMULATED]" not in live_txt
    assert "[SIMULATED]" in sim_txt
