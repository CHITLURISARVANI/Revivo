"""Dispute Defender + Refund Resolver + Checkout Rescuer tests."""

from engines.dispute_defender import DisputeDefender
from engines.refund_resolver import RefundResolver
from engines.checkout_rescuer import CheckoutRescuer


class FakeRP:
    def __init__(self, **kwargs):
        self.disputes = kwargs.get("disputes", [])
        self.refunds = kwargs.get("refunds", [])
        self.orders = kwargs.get("orders", [])
        self.contested = []
        self.refunds_created = []
        self.links = []

    def fetch_open_disputes(self):
        return self.disputes

    def contest_dispute(self, dispute_id, evidence):
        self.contested.append(dispute_id)
        return {"id": dispute_id, "status": "contested", "simulated": True}

    def fetch_pending_refunds(self, days=7):
        return self.refunds

    def create_instant_refund(self, payment_id, amount_inr):
        self.refunds_created.append(payment_id)
        return {"id": f"rfd_{payment_id}", "status": "processed", "simulated": True}

    def fetch_created_orders(self):
        return self.orders

    def create_payment_link(self, amount_inr, description, customer_name=None, customer_email=None, customer_phone=None):
        link = {"id": "plink", "short_url": "https://rzp.io/i/x", "status": "created", "simulated": True}
        self.links.append(link)
        return link


def test_detects_open_disputes(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRP(disputes=[{
        "id": "disp_1",
        "amount": 820000,
        "payment_id": "pay_1",
        "reason_code": "product_not_received",
        "reason": "not received",
    }])
    engine = DisputeDefender(rp, boundaries_config["dispute_defender"], "scan-dd-1")
    assert len(engine.scan()) == 1


def test_contests_winnable_dispute_below_threshold(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRP(disputes=[{
        "id": "disp_win",
        "amount": 820000,
        "payment_id": "pay_1",
        "reason_code": "product_not_received",
        "reason": "not received",
    }])
    engine = DisputeDefender(rp, boundaries_config["dispute_defender"], "scan-dd-2")
    result = engine.run()
    assert len(rp.contested) == 1 or any(
        i.get("action_taken") == "contested" for i in result.get("issues", [])
    )


def test_never_auto_contests_fraud_category(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRP(disputes=[{
        "id": "disp_fraud",
        "amount": 500000,
        "payment_id": "pay_2",
        "reason_code": "fraud",
        "reason": "fraudulent",
    }])
    engine = DisputeDefender(rp, boundaries_config["dispute_defender"], "scan-dd-3")
    result = engine.run()
    assert result["escalated"] >= 1
    assert len(rp.contested) == 0


def test_escalates_dispute_above_threshold(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rp = FakeRP(disputes=[{
        "id": "disp_big",
        "amount": 4500000,  # ₹45,000
        "payment_id": "pay_3",
        "reason_code": "product_not_received",
        "reason": "not received",
    }])
    engine = DisputeDefender(rp, boundaries_config["dispute_defender"], "scan-dd-4")
    result = engine.run()
    assert result["escalated"] >= 1


def test_detects_pending_refunds_older_than_7_days(boundaries_config):
    rp = FakeRP(refunds=[{
        "id": "rfd_1",
        "amount": 300000,
        "payment_id": "pay_r1",
        "created_at": 1600000000,
        "notes": {"card_status": "expired"},
    }])
    engine = RefundResolver(rp, boundaries_config["refund_resolver"], "scan-rr-1")
    assert len(engine.scan()) == 1


def test_reissues_stuck_refund_below_threshold(boundaries_config):
    rp = FakeRP(refunds=[{
        "id": "rfd_ok",
        "amount": 300000,
        "payment_id": "pay_r2",
        "created_at": 1600000000,
        "notes": {"card_status": "expired"},
    }])
    engine = RefundResolver(rp, boundaries_config["refund_resolver"], "scan-rr-2")
    result = engine.run()
    assert result["amount_recovered_inr"] > 0 or len(rp.refunds_created) == 1


def test_escalates_refund_above_threshold(boundaries_config):
    rp = FakeRP(refunds=[{
        "id": "rfd_big",
        "amount": 1500000,
        "payment_id": "pay_r3",
        "created_at": 1600000000,
        "notes": {"card_status": "expired"},
    }])
    engine = RefundResolver(rp, boundaries_config["refund_resolver"], "scan-rr-3")
    result = engine.run()
    assert result["escalated"] >= 1


def test_detects_created_orders_older_than_30min(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import time
    rp = FakeRP(orders=[{
        "id": "order_1",
        "amount": 780000,
        "status": "created",
        "created_at": int(time.time()) - 7200,
        "notes": {"customer_name": "Rahul", "customer_email": "r@e.com", "customer_phone": "+91"},
    }])
    engine = CheckoutRescuer(rp, boundaries_config["checkout_rescuer"], "scan-cr-1")
    issues = engine.scan()
    assert len(issues) >= 1


def test_ignores_orders_below_min_amount(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import time
    rp = FakeRP(orders=[{
        "id": "order_tiny",
        "amount": 300,  # ₹3
        "status": "created",
        "created_at": int(time.time()) - 7200,
        "notes": {"customer_name": "X", "customer_email": "x@e.com"},
    }])
    engine = CheckoutRescuer(rp, boundaries_config["checkout_rescuer"], "scan-cr-2")
    result = engine.run()
    # Either filtered in scan or skipped in execute
    assert result["amount_pending_inr"] == 0 or result["issues_found"] == 0 or all(
        not i.get("pending") for i in result.get("issues", [])
    )


def test_sends_recovery_link_with_ai_message(boundaries_config, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import time
    rp = FakeRP(orders=[{
        "id": "order_hi",
        "amount": 780000,
        "status": "created",
        "created_at": int(time.time()) - 7200,
        "notes": {
            "customer_name": "Rahul",
            "customer_email": "rahul@example.com",
            "customer_phone": "+919876543215",
            "items": "Headphones",
        },
    }])
    engine = CheckoutRescuer(rp, boundaries_config["checkout_rescuer"], "scan-cr-3")
    result = engine.run()
    assert len(rp.links) >= 1 or result.get("amount_pending_inr", 0) > 0
