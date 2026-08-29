"""FastAPI endpoint tests via httpx / TestClient."""

import os
from fastapi.testclient import TestClient


def test_health_and_scan_flow(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    # Import app after env is set for DB
    from server import app

    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"

    r = client.post("/api/scan")
    assert r.status_code == 200
    data = r.json()
    scan_id = data["scan_run_id"]
    assert data["summary"]["issues_found"] > 0

    r = client.get(f"/api/scan/{scan_id}")
    assert r.status_code == 200

    r = client.get("/api/issues")
    assert r.status_code == 200
    assert r.json()["total"] > 0

    issue_id = r.json()["issues"][0]["id"]
    r = client.get(f"/api/issue/{issue_id}")
    assert r.status_code == 200

    r = client.get("/api/escalations")
    assert r.status_code == 200

    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert r.json()["has_data"] is True

    r = client.get(f"/api/audit/{scan_id}")
    assert r.status_code == 200
    assert r.json()["entry_count"] > 0

    r = client.get("/api/boundaries")
    assert r.status_code == 200

    r = client.get("/")
    assert r.status_code == 200
