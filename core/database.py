"""
Database layer for Reclaim — AI Revenue Recovery Agent.
SQLite-based, schema auto-initialized on first run.
"""

import sqlite3
import os
from typing import Optional

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reclaim.db"
)


def get_db_path() -> str:
    """Resolve DB path (override with RECLAIM_DB_PATH for tests)."""
    return os.environ.get("RECLAIM_DB_PATH", _DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    """Get a SQLite connection. Creates DB if it doesn't exist."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialize all tables. Safe to call multiple times."""
    conn = get_connection()
    cursor = conn.cursor()

    # Scan runs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_payments_scanned INTEGER DEFAULT 0,
            total_issues_found INTEGER DEFAULT 0,
            total_amount_at_risk_inr REAL DEFAULT 0,
            total_amount_recovered_inr REAL DEFAULT 0,
            total_escalations INTEGER DEFAULT 0,
            status TEXT DEFAULT 'in_progress'
        )
    """)

    # Issues found during scans
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
            engine TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            razorpay_entity_id TEXT NOT NULL,
            razorpay_entity_type TEXT NOT NULL,
            amount_inr REAL NOT NULL,
            status TEXT DEFAULT 'detected',
            ai_classification TEXT,
            ai_confidence REAL,
            ai_reasoning TEXT,
            action_taken TEXT,
            action_result TEXT,
            amount_recovered_inr REAL DEFAULT 0,
            retry_count INTEGER DEFAULT 0,
            detected_at TEXT NOT NULL,
            resolved_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Escalations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS escalations (
            id TEXT PRIMARY KEY,
            scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
            issue_id TEXT NOT NULL REFERENCES issues(id),
            engine TEXT NOT NULL,
            reason TEXT NOT NULL,
            amount_inr REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            merchant_notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Audit ledger — append-only
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_entries (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
            engine TEXT NOT NULL,
            phase TEXT NOT NULL,
            razorpay_entity_id TEXT,
            issue_type TEXT,
            amount_inr REAL,
            action_taken TEXT,
            action_result TEXT,
            amount_recovered_inr REAL DEFAULT 0,
            ai_reasoning TEXT,
            boundary_check TEXT,
            razorpay_api_called TEXT,
            razorpay_api_response TEXT,
            human_readable TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_issues_scan_run ON issues(scan_run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_issues_engine ON issues(engine)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_scan_run ON audit_entries(scan_run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_entries(razorpay_entity_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status)")

    conn.commit()
    conn.close()


def reset_db() -> None:
    """Delete the database file and reinitialize. Useful for demo resets."""
    path = get_db_path()
    if os.path.exists(path):
        os.remove(path)
    init_db()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {get_db_path()}")
