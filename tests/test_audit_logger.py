"""Audit logger tests."""

import pytest
from core.database import init_db, get_connection
from core.audit_logger import log, get_audit_trail


def test_log_inserts_entry():
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("scan-1", "2025-01-01T00:00:00Z", "in_progress"),
    )
    conn.commit()
    conn.close()

    entry_id = log(
        scan_run_id="scan-1",
        engine="capture_guardian",
        phase="detect",
        human_readable="Found authorized payment",
        amount_inr=12000,
    )
    assert entry_id

    trail = get_audit_trail("scan-1")
    assert len(trail) == 1
    assert trail[0]["human_readable"] == "Found authorized payment"


def test_log_is_append_only():
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("scan-2", "2025-01-01T00:00:00Z", "in_progress"),
    )
    conn.commit()
    conn.close()

    entry_id = log(
        scan_run_id="scan-2",
        engine="retry_strategist",
        phase="diagnose",
        human_readable="Classified as transient",
    )

    # Application contract: audit is append-only — we never UPDATE via logger.
    # Verify INSERT works and UPDATE would require raw SQL (not exposed).
    trail = get_audit_trail("scan-2")
    assert len(trail) == 1
    assert trail[0]["id"] == entry_id

    # Second log creates a new entry, does not mutate first
    log(
        scan_run_id="scan-2",
        engine="retry_strategist",
        phase="execute",
        human_readable="Retry link sent",
    )
    trail = get_audit_trail("scan-2")
    assert len(trail) == 2
    assert trail[0]["human_readable"] == "Classified as transient"


def test_human_readable_field_populated():
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("scan-3", "2025-01-01T00:00:00Z", "in_progress"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(TypeError):
        # human_readable is required
        log(scan_run_id="scan-3", engine="x", phase="detect")  # type: ignore
