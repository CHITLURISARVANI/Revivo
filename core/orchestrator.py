"""
Orchestrator — coordinates all 5 engines, aggregates results, manages scan lifecycle.
"""

import uuid
from datetime import datetime, timezone
from core.database import get_connection, init_db
from core.audit_logger import log as audit_log
from core.boundary_enforcer import load_boundaries
from core.issue_store import save_issue, save_escalation, rebuild_scan_payload
from razorpay_client.client import RazorpayClient

from engines.capture_guardian import CaptureGuardian
from engines.retry_strategist import RetryStrategist
from engines.dispute_defender import DisputeDefender
from engines.refund_resolver import RefundResolver
from engines.checkout_rescuer import CheckoutRescuer


def run_scan() -> dict:
    """
    Run a full scan across all enabled engines.
    Creates a scan run record, executes all engines, aggregates results.

    Returns:
        dict with scan_run_id, summary, and per-engine results.
    """
    # Ensure DB is initialized
    init_db()

    # Create scan run record
    scan_run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, 'in_progress')",
        (scan_run_id, started_at),
    )
    conn.commit()
    conn.close()

    # Log scan start
    audit_log(
        scan_run_id=scan_run_id,
        engine="orchestrator",
        phase="detect",
        human_readable=f"Scan started at {started_at}",
    )

    # Initialize
    razorpay = RazorpayClient()
    config = load_boundaries()

    # Initialize engines
    engine_classes = [
        ("capture_guardian", CaptureGuardian),
        ("retry_strategist", RetryStrategist),
        ("dispute_defender", DisputeDefender),
        ("refund_resolver", RefundResolver),
        ("checkout_rescuer", CheckoutRescuer),
    ]

    all_results = []
    total_recovered = 0
    total_pending = 0
    total_at_risk = 0
    total_issues = 0
    total_escalations = 0
    total_scanned = 0

    for engine_name, engine_class in engine_classes:
        engine_config = config.get(engine_name, {"enabled": False})

        if not engine_config.get("enabled", False):
            all_results.append({
                "engine": engine_name,
                "scanned": 0,
                "issues_found": 0,
                "skipped": True,
            })
            continue

        engine = engine_class(razorpay, engine_config, scan_run_id)
        result = engine.run()

        all_results.append(result)
        total_scanned += result.get("scanned", 0)
        total_issues += result.get("issues_found", 0)
        total_recovered += result.get("amount_recovered_inr", 0)
        total_pending += result.get("amount_pending_inr", 0)
        total_escalations += result.get("escalated", 0)

        # Persist issues + escalations for API queries
        for issue in result.get("issues", []):
            total_at_risk += issue.get("amount_inr", 0)
            issue_id = save_issue(scan_run_id, issue)
            if issue.get("escalated"):
                save_escalation(
                    scan_run_id=scan_run_id,
                    issue_id=issue_id,
                    engine=issue.get("engine", engine_name),
                    reason=issue.get("reason", issue.get("action_taken", "escalated")),
                    amount_inr=issue.get("amount_inr", 0),
                )

    completed_at = datetime.now(timezone.utc).isoformat()

    # Update scan run record
    conn = get_connection()
    conn.execute(
        """
        UPDATE scan_runs
        SET completed_at = ?, status = 'completed',
            total_payments_scanned = ?, total_issues_found = ?,
            total_amount_at_risk_inr = ?, total_amount_recovered_inr = ?,
            total_amount_pending_inr = ?,
            total_escalations = ?
        WHERE id = ?
        """,
        (completed_at, total_scanned, total_issues,
         total_at_risk, total_recovered, total_pending, total_escalations,
         scan_run_id),
    )
    conn.commit()
    conn.close()

    # Log scan completion
    audit_log(
        scan_run_id=scan_run_id,
        engine="orchestrator",
        phase="resolve",
        action_result="completed",
        amount_recovered_inr=total_recovered,
        human_readable=f"Scan completed. Scanned: {total_scanned}, Issues: {total_issues}, "
                      f"At risk: ₹{total_at_risk:,.0f}, Recovered: ₹{total_recovered:,.0f}, "
                      f"Pending: ₹{total_pending:,.0f}, Escalated: {total_escalations}",
    )

    return {
        "scan_run_id": scan_run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "completed",
        "summary": {
            "payments_scanned": total_scanned,
            "issues_found": total_issues,
            "amount_at_risk_inr": round(total_at_risk, 2),
            "amount_recovered_inr": round(total_recovered, 2),
            "amount_pending_inr": round(total_pending, 2),
            "escalations": total_escalations,
            "engines_run": [r["engine"] for r in all_results if not r.get("skipped")],
            "engines_skipped": [r["engine"] for r in all_results if r.get("skipped")],
        },
        "engines": all_results,
        "razorpay_mode": "simulated" if razorpay.is_simulated() else "live",
    }


def get_scan_result(scan_run_id: str) -> dict:
    """Get the results of a specific scan run."""
    conn = get_connection()
    run = conn.execute(
        "SELECT * FROM scan_runs WHERE id = ?",
        (scan_run_id,),
    ).fetchone()

    if not run:
        conn.close()
        return {"error": "Scan run not found", "scan_run_id": scan_run_id}

    # Get audit trail
    audit_entries = conn.execute(
        "SELECT * FROM audit_entries WHERE scan_run_id = ? ORDER BY timestamp ASC",
        (scan_run_id,),
    ).fetchall()

    conn.close()

    return {
        "scan_run": dict(run),
        "audit_trail": [dict(e) for e in audit_entries],
    }


def get_dashboard_data() -> dict:
    """Get aggregated data for the dashboard, including a rebuildable scan payload."""
    conn = get_connection()

    # Latest scan run
    latest = conn.execute(
        "SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    if not latest:
        conn.close()
        return {
            "has_data": False,
            "message": "No scans run yet. Click 'Scan Now' to start.",
        }

    latest_id = latest["id"]

    # Recent audit entries
    audit_entries = conn.execute(
        "SELECT * FROM audit_entries WHERE scan_run_id = ? ORDER BY timestamp ASC",
        (latest_id,),
    ).fetchall()

    # All-time stats
    totals = conn.execute(
        "SELECT COUNT(*) as count, SUM(total_amount_recovered_inr) as recovered, "
        "SUM(total_issues_found) as issues FROM scan_runs WHERE status = 'completed'"
    ).fetchone()

    conn.close()

    payload = rebuild_scan_payload(latest_id)

    return {
        "has_data": True,
        "latest_scan": dict(latest),
        "scan_payload": payload,
        "audit_trail": [dict(e) for e in audit_entries],
        "all_time": {
            "total_scans": totals["count"] if totals else 0,
            "total_recovered": totals["recovered"] if totals else 0,
            "total_issues": totals["issues"] if totals else 0,
        },
    }
