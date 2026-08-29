"""Winnability + evidence + message gen tests."""

from ai.winnability import score_dispute_winnability
from ai.evidence_gen import generate_dispute_evidence
from ai.message_gen import generate_recovery_message


def test_product_not_received_with_tracking_scores_high(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = score_dispute_winnability({
        "reason_code": "product_not_received",
        "available_evidence": {
            "has_tracking_number": True,
            "tracking_number": "DL123456",
            "delivery_date": "2025-03-15",
            "delivery_signed_by": "Rajesh",
        },
    })
    assert result["winnability_score"] >= 0.8
    assert result["recommendation"] == "contest"


def test_fraud_dispute_scores_low(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = score_dispute_winnability({
        "reason_code": "fraud",
        "available_evidence": {},
    })
    assert result["winnability_score"] < 0.5
    assert result["recommendation"] == "escalate"


def test_evidence_contains_tracking_number(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dispute = {
        "reason_code": "product_not_received",
        "amount": 820000,
        "available_evidence": {
            "has_tracking_number": True,
            "tracking_number": "DL123456",
            "delivery_date": "2025-03-15",
            "delivery_signed_by": "Rajesh",
        },
    }
    winnability = score_dispute_winnability(dispute)
    evidence = generate_dispute_evidence(dispute, winnability)
    assert "DL123456" in evidence["contest_text"]
    assert evidence["evidence_documents"]


def test_evidence_is_structured_for_razorpay_api(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dispute = {
        "reason_code": "product_not_received",
        "amount": 820000,
        "available_evidence": {
            "has_tracking_number": True,
            "tracking_number": "DL123456",
            "delivery_date": "2025-03-15",
            "delivery_signed_by": "Rajesh",
        },
    }
    evidence = generate_dispute_evidence(dispute, {"recommendation": "contest"})
    assert "contest_text" in evidence
    assert "evidence_documents" in evidence
    assert "summary" in evidence


def test_message_contains_order_amount(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    msg = generate_recovery_message(
        {"amount_inr": 7800, "items": "Headphones"},
        {"name": "Rahul"},
        "https://rzp.io/i/abc123",
    )
    assert "7800" in msg["message"] or "7,800" in msg["message"]


def test_message_contains_payment_link(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    link = "https://rzp.io/i/abc123"
    msg = generate_recovery_message(
        {"amount_inr": 7800},
        {"name": "Rahul"},
        link,
    )
    assert link in msg["message"]


def test_message_is_hinglish(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    msg = generate_recovery_message(
        {"amount_inr": 7800},
        {"name": "Rahul"},
        "https://rzp.io/i/abc",
    )
    assert msg["language"] == "hinglish"
    assert "pending" in msg["message"].lower() or "order" in msg["message"].lower()


def test_fallback_message_when_api_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    msg = generate_recovery_message(
        {"amount_inr": 1500},
        {"name": "Priya"},
        "https://rzp.io/i/xyz",
    )
    assert msg["message"]
    assert msg["channel"] == "sms"
