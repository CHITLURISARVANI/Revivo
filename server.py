"""
Revivo — AI Revenue Recovery Agent
FastAPI server with all endpoints.

Run: python server.py
"""

import os
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from core.orchestrator import run_scan, get_scan_result, get_dashboard_data
from core.boundary_enforcer import load_boundaries, save_boundaries
from core.database import init_db, reset_db
from core.audit_logger import get_audit_trail
from core.issue_store import (
    list_issues,
    get_issue,
    list_escalations,
    resolve_escalation,
)

# Initialize DB on startup
init_db()

app = FastAPI(title="Revivo — AI Revenue Recovery Agent", version="1.0.0")

# Serve dashboard files
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


# ─── Models ───

class BoundaryUpdate(BaseModel):
    capture_guardian: Optional[dict] = None
    retry_strategist: Optional[dict] = None
    dispute_defender: Optional[dict] = None
    refund_resolver: Optional[dict] = None
    checkout_rescuer: Optional[dict] = None


class EscalationResolve(BaseModel):
    action: str  # "approve" | "dismiss"
    notes: Optional[str] = None


# ─── Endpoints ───

ASSET_VERSION = "20260830b6"


def _serve_index_html() -> HTMLResponse:
    """Serve dashboard HTML with cache-busted assets. Rules are baked into HTML."""
    import re

    index_path = DASHBOARD_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard/index.html missing</p>",
            status_code=404,
        )
    html = index_path.read_text(encoding="utf-8")
    html = re.sub(
        r"/static/app\.js(?:\?v=[^\s\"']*)?",
        f"/static/app.js?v={ASSET_VERSION}",
        html,
    )
    html = re.sub(
        r"/static/style\.css(?:\?v=[^\s\"']*)?",
        f"/static/style.css?v={ASSET_VERSION}",
        html,
    )
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/")
def root():
    """Serve the demo website (new-user landing + live workspace)."""
    if DASHBOARD_DIR.exists():
        return _serve_index_html()
    return JSONResponse({
        "name": "Revivo — AI Revenue Recovery Agent",
        "version": "1.0.0",
        "message": "Dashboard missing. Open /docs for API.",
    })


@app.get("/api")
def api_info():
    """Service / API info."""
    return {
        "name": "Revivo — AI Revenue Recovery Agent",
        "version": "1.0.0",
        "tagline": "Find money merchants don't know they're losing — and recover it.",
        "website": "/",
        "dashboard": "/dashboard",
        "endpoints": [
            "GET  / — website",
            "GET  /dashboard — website",
            "GET  /health — health check",
            "POST /api/scan — trigger a full scan",
            "POST /api/seed — refresh synthetic demo dataset",
            "GET  /api/scan/{scan_run_id} — get scan results",
            "GET  /api/issues — list issues",
            "GET  /api/issue/{id} — issue detail",
            "GET  /api/escalations — pending escalations",
            "POST /api/escalation/{id}/resolve — resolve escalation",
            "GET  /api/dashboard — dashboard data",
            "GET  /api/audit/{scan_run_id} — audit trail",
            "GET  /api/boundaries — get boundary config",
            "PUT  /api/boundaries — update boundary config",
            "POST /api/reset — reset database (demo only)",
        ],
    }


@app.get("/health")
def health():
    """Health check."""
    from razorpay_client.client import RazorpayClient
    rp = RazorpayClient()
    return {
        "status": "healthy",
        "razorpay_api": "simulated" if rp.is_simulated() else "connected",
        "ai_api": "connected" if os.getenv("OPENAI_API_KEY") else "fallback",
        "database": "connected",
        "version": "1.0.0",
    }


@app.post("/api/scan")
def trigger_scan():
    """Trigger a full scan across all enabled engines."""
    result = run_scan()
    return result


@app.post("/api/seed")
def seed_demo_data():
    """
    Refresh data/synthetic_payments.json (all 5 leak types).
    Used by 'Continue with demo data'. Falls back to JSON when Razorpay keys absent.
    """
    from scripts.seed_test_data import build_dataset, write_json, seed_razorpay_test_mode

    dataset = build_dataset()
    path = write_json(dataset)
    rzp = seed_razorpay_test_mode(dataset)
    return {
        "status": "ok",
        "path": str(path),
        "razorpay_seed": rzp,
        "counts": {
            "payments": len(dataset.get("payments", [])),
            "disputes": len(dataset.get("disputes", [])),
            "refunds": len(dataset.get("refunds", [])),
            "orders": len(dataset.get("orders", [])),
        },
    }


@app.get("/api/scan/{scan_run_id}")
def get_scan(scan_run_id: str):
    """Get results of a specific scan run."""
    result = get_scan_result(scan_run_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/dashboard")
def dashboard_data():
    """Get aggregated data for the dashboard."""
    return get_dashboard_data()


@app.get("/api/issues")
def issues_list(
    status: Optional[str] = None,
    engine: Optional[str] = None,
    scan_run_id: Optional[str] = None,
    limit: int = 50,
    cursor: int = 0,
):
    """List issues with optional filters and pagination."""
    return list_issues(
        status=status,
        engine=engine,
        scan_run_id=scan_run_id,
        limit=min(limit, 200),
        cursor=max(cursor, 0),
    )


@app.get("/api/issue/{issue_id}")
def issue_detail(issue_id: str):
    """Get full detail for a single issue including audit trail."""
    result = get_issue(issue_id)
    if not result:
        raise HTTPException(status_code=404, detail="Issue not found")
    return result


@app.get("/api/escalations")
def escalations_list(status: Optional[str] = "pending", limit: int = 50):
    """List escalations needing human review."""
    items = list_escalations(status=status, limit=min(limit, 200))
    return {"count": len(items), "escalations": items}


@app.post("/api/escalation/{escalation_id}/resolve")
def escalation_resolve(escalation_id: str, body: EscalationResolve):
    """Merchant approves or dismisses an escalation."""
    try:
        result = resolve_escalation(escalation_id, body.action, body.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {"status": "ok", "escalation": result}


@app.get("/api/audit/{scan_run_id}")
def audit_trail(scan_run_id: str):
    """Get the full audit trail for a scan run."""
    entries = get_audit_trail(scan_run_id)
    return {
        "scan_run_id": scan_run_id,
        "entry_count": len(entries),
        "entries": entries,
    }


@app.get("/api/boundaries")
def get_boundaries():
    """Get current boundary configuration."""
    return load_boundaries()


@app.put("/api/boundaries")
def update_boundaries(update: BoundaryUpdate):
    """Update boundary configuration."""
    config = load_boundaries()
    update_dict = update.model_dump(exclude_none=True)
    for key, value in update_dict.items():
        if key in config:
            config[key].update(value)

    save_boundaries(config)
    return {"status": "updated", "config": config}


@app.post("/api/reset")
def reset_database():
    """Reset the database. Demo only — clears all scan runs and audit entries."""
    reset_db()
    return {"status": "reset", "message": "Database cleared. Ready for fresh scan."}


@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the web dashboard."""
    return _serve_index_html()


if __name__ == "__main__":
    import uvicorn
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Revivo — AI Revenue Recovery Agent                         ║")
    print("║  Razorpay AI Buildathon 2026 — Track 03                     ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  Dashboard: http://localhost:8000/dashboard                  ║")
    print("║  API:       http://localhost:8000/                           ║")
    print("║  Docs:      http://localhost:8000/docs                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    uvicorn.run(app, host="0.0.0.0", port=8000)
