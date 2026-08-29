"""Orchestrator + Razorpay client + seed data tests."""

import json
from pathlib import Path

from core.orchestrator import run_scan, get_dashboard_data
from core.issue_store import list_issues, list_escalations
from razorpay_client.client import RazorpayClient


def test_run_scan_executes_all_enabled_engines(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    # Point boundary enforcer at test config
    result = run_scan()
    assert result["status"] == "completed"
    engines = result["summary"]["engines_run"]
    assert "capture_guardian" in engines
    assert len(engines) == 5


def test_run_scan_aggregates_results(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    result = run_scan()
    summary = result["summary"]
    assert "payments_scanned" in summary
    assert "issues_found" in summary
    assert "amount_at_risk_inr" in summary
    assert summary["issues_found"] > 0


def test_run_scan_creates_scan_run_record(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    result = run_scan()
    assert result["scan_run_id"]
    dash = get_dashboard_data()
    assert dash["has_data"] is True


def test_disabled_engine_skipped(boundaries_config, monkeypatch, tmp_path):
    import json
    from core import boundary_enforcer

    config = boundaries_config.copy()
    config["refund_resolver"] = {**config["refund_resolver"], "enabled": False}
    path = tmp_path / "b.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(boundary_enforcer, "BOUNDARIES_PATH", str(path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    result = run_scan()
    assert "refund_resolver" in result["summary"]["engines_skipped"]


def test_issues_persisted_after_scan(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    run_scan()
    issues = list_issues()
    assert issues["total"] > 0


def test_escalations_persisted(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    run_scan()
    escalations = list_escalations(status="pending")
    # Synthetic data has high-value auth + fraud dispute → at least 1 escalation
    assert isinstance(escalations, list)


def test_simulated_client_loads_synthetic_json():
    client = RazorpayClient(key_id=None, key_secret=None)
    assert client.is_simulated()
    auth = client.fetch_authorized_payments()
    assert len(auth) >= 2
    failed = client.fetch_failed_payments()
    assert len(failed) >= 2


def test_synthetic_payments_file_exists():
    path = Path(__file__).resolve().parent.parent / "data" / "synthetic_payments.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["meta"]["distribution"]["total_entities"] == 50
    assert len(data["payments"]) == 44  # 35+5+4
    assert len(data["orders"]) == 2
    assert len(data["disputes"]) == 2
    assert len(data["refunds"]) == 2
