"""E2E: seed → scan → recovery → audit (plan.md critical path)."""

from scripts.seed_test_data import build_dataset, write_json
from core.orchestrator import run_scan
from core.audit_logger import get_audit_trail
from core.issue_store import list_issues, rebuild_scan_payload


def test_e2e_seed_scan_recovery_audit(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    dataset = build_dataset()
    write_json(dataset)

    assert len(dataset["payments"]) >= 40
    assert any(p.get("status") == "authorized" for p in dataset["payments"])
    assert any(p.get("status") == "failed" for p in dataset["payments"])
    assert len(dataset["disputes"]) >= 1
    assert len(dataset["refunds"]) >= 1
    assert len(dataset["orders"]) >= 1

    result = run_scan()
    summary = result["summary"]
    assert summary["issues_found"] > 0
    assert summary["amount_at_risk_inr"] > 0
    assert summary["amount_recovered_inr"] + summary["amount_pending_inr"] > 0
    assert len(result["engines"]) == 5

    engines_run = {e["engine"] for e in result["engines"] if not e.get("skipped")}
    assert "capture_guardian" in engines_run
    assert "retry_strategist" in engines_run

    issues = list_issues(scan_run_id=result["scan_run_id"], limit=200)
    assert issues["total"] > 0

    trail = get_audit_trail(result["scan_run_id"])
    assert len(trail) > 5
    phases = {e["phase"] for e in trail}
    assert "detect" in phases
    assert "execute" in phases or "escalate" in phases
    assert any("Captured payment" in (e.get("human_readable") or "") for e in trail)

    payload = rebuild_scan_payload(result["scan_run_id"])
    assert payload is not None
    assert payload["summary"]["issues_found"] == summary["issues_found"]
    assert payload["engines"]


def test_seed_endpoint(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/api/seed")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["counts"]["payments"] > 0
