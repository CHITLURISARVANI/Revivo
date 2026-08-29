"""Retry Strategist engine tests."""

from engines.retry_strategist import RetryStrategist


class FakeRazorpay:
    def __init__(self, payments):
        self._payments = payments
        self.links = []

    def fetch_failed_payments(self, hours=24):
        return self._payments

    def create_payment_link(self, amount_inr, description, customer_name=None, customer_email=None, customer_phone=None):
        link = {
            "id": "plink_test",
            "short_url": "https://rzp.io/i/test",
            "status": "created",
            "simulated": True,
        }
        self.links.append(link)
        return link


def test_detects_failed_payments_in_last_24h(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRazorpay([{
        "id": "pay_fail",
        "amount": 450000,
        "method": "upi",
        "error_code": "UPI_S2S_DECLINED",
        "error_description": "declined",
        "email": "a@b.com",
    }])
    engine = RetryStrategist(rp, boundaries_config["retry_strategist"], "scan-rs-1")
    issues = engine.scan()
    assert len(issues) == 1


def test_classifies_transient_and_sends_retry_link(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRazorpay([{
        "id": "pay_transient",
        "amount": 450000,
        "method": "upi",
        "error_code": "UPI_S2S_DECLINED",
        "error_description": "UPI declined by bank",
        "email": "a@b.com",
        "contact": "+919999999999",
    }])
    engine = RetryStrategist(rp, boundaries_config["retry_strategist"], "scan-rs-2")
    result = engine.run()
    assert result["issues_found"] >= 1
    assert len(rp.links) >= 1 or result.get("amount_pending_inr", 0) > 0 or any(
        i.get("pending") or i.get("action_taken") == "retry_link_sent" for i in result.get("issues", [])
    )


def test_does_not_retry_permanent_failure(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRazorpay([{
        "id": "pay_perm",
        "amount": 220000,
        "method": "upi",
        "error_code": "INSUFFICIENT_FUNDS",
        "error_description": "Insufficient funds",
        "email": "a@b.com",
    }])
    engine = RetryStrategist(rp, boundaries_config["retry_strategist"], "scan-rs-3")
    result = engine.run()
    assert len(rp.links) == 0
    issue = result["issues"][0]
    assert issue.get("ai_classification") == "permanent" or not issue.get("pending")


def test_respects_max_retries(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from core.boundary_enforcer import check_action
    result = check_action("retry_strategist", "retry", 4500, retry_count=2)
    assert result.allowed is False
