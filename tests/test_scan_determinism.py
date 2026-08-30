"""Deterministic scan results on the same seeded demo data."""

from scripts.seed_test_data import build_dataset, write_json
from core.orchestrator import run_scan


def _summary_key(result: dict) -> tuple:
    s = result["summary"]
    return (
        s["payments_scanned"],
        s["issues_found"],
        round(s["amount_recovered_inr"], 2),
        round(s["amount_pending_inr"], 2),
        s["escalations"],
    )


def test_three_scans_identical_on_same_seed(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    write_json(build_dataset())

    a = _summary_key(run_scan())
    b = _summary_key(run_scan())
    c = _summary_key(run_scan())

    assert a == b == c
    assert a[0] > 0  # scanned
    assert a[1] > 0  # issues
    assert a[2] > 0  # recovered
    assert a[3] > 0  # pending (checkout/retry links)
