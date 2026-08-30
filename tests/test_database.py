"""Database layer tests."""

from core.database import init_db, get_connection, get_db_path


def test_scan_runs_table_exists():
    init_db()
    conn = get_connection()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "scan_runs" in tables
    assert "issues" in tables
    assert "escalations" in tables
    assert "audit_entries" in tables


def test_db_path_uses_env(monkeypatch, tmp_path):
    path = tmp_path / "custom.db"
    monkeypatch.setenv("Revivo_DB_PATH", str(path))
    assert get_db_path() == str(path)


def test_insert_scan_run():
    init_db()
    conn = get_connection()
    conn.execute(
        "INSERT INTO scan_runs (id, started_at, status) VALUES (?, ?, ?)",
        ("run-1", "2025-01-01T00:00:00Z", "in_progress"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM scan_runs WHERE id = ?", ("run-1",)).fetchone()
    conn.close()
    assert row["status"] == "in_progress"
