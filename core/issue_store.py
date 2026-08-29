"""
Issue & Escalation store — persist scan outcomes for API/dashboard queries.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from core.database import get_connection


def save_issue(scan_run_id: str, outcome: dict) -> str:
    """Persist an engine outcome as an issue row. Returns issue id."""
    issue_id = outcome.get("issue_id") or outcome.get("id") or str(uuid.uuid4())
    entity_id = (
        outcome.get("razorpay_entity_id")
        or outcome.get("payment_id")
        or outcome.get("dispute_id")
        or outcome.get("order_id")
        or outcome.get("refund_id")
        or "unknown"
    )
    entity_type = outcome.get("razorpay_entity_type") or _infer_entity_type(entity_id, outcome)
    status = _status_from_outcome(outcome)
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO issues (
            id, scan_run_id, engine, issue_type, razorpay_entity_id,
            razorpay_entity_type, amount_inr, status, ai_classification,
            ai_confidence, ai_reasoning, action_taken, action_result,
            amount_recovered_inr, retry_count, detected_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            issue_id,
            scan_run_id,
            outcome.get("engine", "unknown"),
            outcome.get("issue_type", "unknown"),
            entity_id,
            entity_type,
            outcome.get("amount_inr", 0),
            status,
            outcome.get("ai_classification"),
            outcome.get("ai_confidence") or outcome.get("ai_winnability_score"),
            outcome.get("ai_reasoning"),
            outcome.get("action_taken"),
            outcome.get("action_result"),
            outcome.get("amount_recovered_inr", 0),
            outcome.get("retry_count", 0),
            now,
            now if status in ("resolved", "lost") else None,
        ),
    )
    conn.commit()
    conn.close()
    return issue_id


def save_escalation(
    scan_run_id: str,
    issue_id: str,
    engine: str,
    reason: str,
    amount_inr: float,
) -> str:
    """Persist an escalation needing human review."""
    esc_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO escalations (
            id, scan_run_id, issue_id, engine, reason, amount_inr, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (esc_id, scan_run_id, issue_id, engine, reason, amount_inr),
    )
    conn.commit()
    conn.close()
    return esc_id


def list_issues(
    status: str = None,
    engine: str = None,
    scan_run_id: str = None,
    limit: int = 50,
    cursor: int = 0,
) -> dict:
    """List issues with optional filters and offset pagination."""
    clauses = []
    params = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if engine:
        clauses.append("engine = ?")
        params.append(engine)
    if scan_run_id:
        clauses.append("scan_run_id = ?")
        params.append(scan_run_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_connection()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM issues {where}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM issues {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?",
        [*params, limit, cursor],
    ).fetchall()
    conn.close()

    next_cursor = cursor + limit if cursor + limit < total else None
    return {
        "total": total,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "issues": [dict(r) for r in rows],
    }


def get_issue(issue_id: str) -> Optional[dict]:
    """Get a single issue with related audit trail."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if not row:
        conn.close()
        return None

    audit = conn.execute(
        """
        SELECT * FROM audit_entries
        WHERE razorpay_entity_id = ?
        ORDER BY timestamp ASC
        """,
        (row["razorpay_entity_id"],),
    ).fetchall()
    escalations = conn.execute(
        "SELECT * FROM escalations WHERE issue_id = ?",
        (issue_id,),
    ).fetchall()
    conn.close()

    return {
        **dict(row),
        "audit_trail": [dict(a) for a in audit],
        "escalations": [dict(e) for e in escalations],
    }


def list_escalations(status: str = "pending", limit: int = 50) -> list[dict]:
    """List escalations, defaulting to pending."""
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM escalations WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM escalations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_escalation(escalation_id: str, action: str, notes: str = None) -> Optional[dict]:
    """
    Resolve an escalation.
    action: 'approve' | 'dismiss'
    """
    if action not in ("approve", "dismiss"):
        raise ValueError("action must be 'approve' or 'dismiss'")

    new_status = "resolved_by_human" if action == "approve" else "dismissed"
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM escalations WHERE id = ?",
        (escalation_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None

    conn.execute(
        "UPDATE escalations SET status = ?, merchant_notes = ? WHERE id = ?",
        (new_status, notes, escalation_id),
    )
    # Mirror on issue
    issue_status = "resolved" if action == "approve" else "lost"
    conn.execute(
        "UPDATE issues SET status = ?, resolved_at = ? WHERE id = ?",
        (issue_status, datetime.now(timezone.utc).isoformat(), row["issue_id"]),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM escalations WHERE id = ?",
        (escalation_id,),
    ).fetchone()
    conn.close()
    return dict(updated) if updated else None


def _status_from_outcome(outcome: dict) -> str:
    if outcome.get("recovered"):
        return "resolved"
    if outcome.get("escalated"):
        return "escalated"
    if outcome.get("pending"):
        return "action_taken"
    if outcome.get("action_result") == "success":
        return "action_taken"
    return "detected"


def _infer_entity_type(entity_id: str, outcome: dict) -> str:
    if outcome.get("issue_type") == "abandoned_checkout" or entity_id.startswith("order_"):
        return "order"
    if entity_id.startswith("disp_"):
        return "dispute"
    if entity_id.startswith("rfd_"):
        return "refund"
    return "payment"
