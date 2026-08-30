"""
Demo clock — fixed reference time for reproducible simulated scans.

Scan state is SERVER-SIDE (shared SQLite). In simulated mode, each scan
re-evaluates the same synthetic dataset against this clock so results are
deterministic across tabs/runs.
"""

from datetime import datetime, timezone

# Frozen "now" for synthetic ages (authorized 8h+, abandoned 1–2h, etc.)
FIXED_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def client_is_simulated(client) -> bool:
    """True only for real RazorpayClient simulated mode (not unit-test fakes)."""
    fn = getattr(client, "is_simulated", None)
    if callable(fn):
        return bool(fn())
    return False


def now_utc(*, simulated: bool = False) -> datetime:
    """Wall clock in live/unit-test mode; fixed clock in simulated demo mode."""
    if simulated:
        return FIXED_NOW
    return datetime.now(timezone.utc)
