"""
Audit Logger — append-only audit trail.
Every detect, diagnose, decide, execute, escalate, resolve is logged.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from core.database import get_connection


def log(
    scan_run_id: str,
    engine: str,
    phase: str,
    human_readable: str,
    razorpay_entity_id: str = None,
    issue_type: str = None,
    amount_inr: float = None,
    action_taken: str = None,
    action_result: str = None,
    amount_recovered_inr: float = 0,
    ai_reasoning: str = None,
    boundary_check: str = None,
    razorpay_api_called: str = None,
    razorpay_api_response: str = None,
) -> str:
    """
    Log an audit entry. Returns the entry ID.

    Args:
        scan_run_id: ID of the current scan run
        engine: Which engine ("capture_guardian", "retry_strategist", etc.)
        phase: "detect" | "diagnose" | "decide" | "execute" | "escalate" | "resolve"
        human_readable: Plain English explanation of what happened
        razorpay_entity_id: Payment/order/dispute/refund ID
        issue_type: Type of issue found
        amount_inr: Amount at stake
        action_taken: What action was taken
        action_result: Result of the action
        amount_recovered_inr: Money recovered (0 if none)
        ai_reasoning: AI's explanation for the decision
        boundary_check: "within_bounds" | "blocked:reason" | "escalated:reason"
        razorpay_api_called: API endpoint called
        razorpay_api_response: HTTP status + response summary
    """
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO audit_entries (
            id, timestamp, scan_run_id, engine, phase,
            razorpay_entity_id, issue_type, amount_inr,
            action_taken, action_result, amount_recovered_inr,
            ai_reasoning, boundary_check,
            razorpay_api_called, razorpay_api_response,
            human_readable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id, timestamp, scan_run_id, engine, phase,
            razorpay_entity_id, issue_type, amount_inr,
            action_taken, action_result, amount_recovered_inr,
            ai_reasoning, boundary_check,
            razorpay_api_called, razorpay_api_response,
            human_readable,
        ),
    )
    conn.commit()
    conn.close()
    return entry_id


def get_audit_trail(scan_run_id: str) -> list[dict]:
    """Get all audit entries for a scan run, ordered by timestamp."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_entries WHERE scan_run_id = ? ORDER BY timestamp ASC",
        (scan_run_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_audit_trail_for_entity(razorpay_entity_id: str) -> list[dict]:
    """Get all audit entries for a specific Razorpay entity (payment/dispute/etc)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_entries WHERE razorpay_entity_id = ? ORDER BY timestamp ASC",
        (razorpay_entity_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
