"""
Razorpay Client Layer — thin wrapper around Razorpay SDK.
All API calls go through here for consistent error handling and logging.
"""

import json
import os
import logging
from pathlib import Path

try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    RAZORPAY_AVAILABLE = False

logger = logging.getLogger(__name__)

SYNTHETIC_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_payments.json"


class RazorpayClient:
    """Wrapper around Razorpay SDK for Reclaim's needs."""

    def __init__(self, key_id: str = None, key_secret: str = None):
        """
        Initialize with explicit keys or from environment variables.

        If no keys provided and not in env, client is in 'simulated' mode —
        all API calls return data from data/synthetic_payments.json
        (with hardcoded fallbacks). Demo works without Razorpay test keys.
        """
        self.key_id = key_id or os.getenv("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET")
        self.simulated = False
        self._synthetic = None

        if not self.key_id or not self.key_secret or not RAZORPAY_AVAILABLE:
            self.simulated = True
            logger.warning(
                "Razorpay client running in SIMULATED mode. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET for live API calls."
            )
        else:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))

    def _load_synthetic(self) -> dict:
        """Load synthetic dataset once (cached)."""
        if self._synthetic is not None:
            return self._synthetic
        if SYNTHETIC_DATA_PATH.exists():
            try:
                self._synthetic = json.loads(SYNTHETIC_DATA_PATH.read_text(encoding="utf-8"))
                return self._synthetic
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load synthetic data: {e}")
        self._synthetic = {}
        return self._synthetic

    # ─── Payments ───

    def fetch_authorized_payments(self) -> list[dict]:
        """Fetch all payments in 'authorized' state."""
        if self.simulated:
            data = self._load_synthetic()
            if data.get("payments"):
                return [p for p in data["payments"] if p.get("status") == "authorized"]
            return self._fallback_authorized_payments()
        try:
            payments = self.client.payment.all({'count': 100})
            all_payments = payments.get('items', payments) if isinstance(payments, dict) else payments
            return [p for p in all_payments if p.get('status') == 'authorized']
        except Exception as e:
            logger.error(f"fetch_authorized_payments failed: {e}")
            return []

    def fetch_failed_payments(self, hours: int = 24) -> list[dict]:
        """Fetch failed payments from the last N hours."""
        if self.simulated:
            data = self._load_synthetic()
            if data.get("payments"):
                return [p for p in data["payments"] if p.get("status") == "failed"]
            return self._fallback_failed_payments()
        try:
            from datetime import datetime, timedelta, timezone
            since = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
            payments = self.client.payment.all({'count': 100, 'from': since})
            all_payments = payments.get('items', payments) if isinstance(payments, dict) else payments
            return [p for p in all_payments if p.get('status') == 'failed']
        except Exception as e:
            logger.error(f"fetch_failed_payments failed: {e}")
            return []

    def capture_payment(self, payment_id: str, amount_inr: float) -> dict:
        """Capture an authorized payment."""
        if self.simulated:
            return {"id": payment_id, "status": "captured", "amount": int(amount_inr * 100), "simulated": True}
        try:
            result = self.client.payment.capture(payment_id, int(amount_inr * 100), "INR")
            return result
        except Exception as e:
            logger.error(f"capture_payment failed for {payment_id}: {e}")
            return {"id": payment_id, "status": "failed", "error": str(e)}

    # ─── Orders ───

    def fetch_created_orders(self) -> list[dict]:
        """Fetch orders in 'created' state (not yet paid)."""
        if self.simulated:
            data = self._load_synthetic()
            return data.get("orders") or self._fallback_created_orders()
        try:
            orders = self.client.order.all({'count': 100})
            all_orders = orders.get('items', orders) if isinstance(orders, dict) else orders
            return [o for o in all_orders if o.get('status') == 'created']
        except Exception as e:
            logger.error(f"fetch_created_orders failed: {e}")
            return []

    # ─── Disputes ───

    def fetch_open_disputes(self) -> list[dict]:
        """Fetch all open disputes."""
        if self.simulated:
            data = self._load_synthetic()
            return data.get("disputes") or self._fallback_open_disputes()
        try:
            disputes = self.client.dispute.all({'count': 100})
            all_disputes = disputes.get('items', disputes) if isinstance(disputes, dict) else disputes
            return [d for d in all_disputes if d.get('status') == 'open']
        except Exception as e:
            logger.error(f"fetch_open_disputes failed: {e}")
            return []

    def contest_dispute(self, dispute_id: str, evidence: dict) -> dict:
        """Contest a dispute with evidence."""
        if self.simulated:
            return {"id": dispute_id, "status": "contested", "simulated": True, "evidence_accepted": True}
        try:
            result = self.client.dispute.contest(dispute_id, evidence)
            return result
        except Exception as e:
            logger.error(f"contest_dispute failed for {dispute_id}: {e}")
            return {"id": dispute_id, "status": "failed", "error": str(e)}

    # ─── Refunds ───

    def fetch_pending_refunds(self, days: int = 7) -> list[dict]:
        """Fetch refunds in 'pending' state older than N days."""
        if self.simulated:
            data = self._load_synthetic()
            return data.get("refunds") or self._fallback_pending_refunds()
        try:
            refunds = self.client.refund.all({'count': 100})
            all_refunds = refunds.get('items', refunds) if isinstance(refunds, dict) else refunds
            pending = [r for r in all_refunds if r.get('status') == 'pending']
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            return [r for r in pending if self._refund_older_than(r, cutoff)]
        except Exception as e:
            logger.error(f"fetch_pending_refunds failed: {e}")
            return []

    def create_instant_refund(self, payment_id: str, amount_inr: float) -> dict:
        """Create an instant refund for a payment."""
        if self.simulated:
            return {
                "id": f"rfd_sim_{payment_id}",
                "status": "processed",
                "simulated": True,
                "amount": int(amount_inr * 100),
            }
        try:
            result = self.client.refund.create({
                "payment_id": payment_id,
                "amount": int(amount_inr * 100),
                "speed": "optimum",
                "currency": "INR",
            })
            return result
        except Exception as e:
            logger.error(f"create_instant_refund failed for {payment_id}: {e}")
            return {"status": "failed", "error": str(e)}

    # ─── Payment Links ───

    def create_payment_link(
        self,
        amount_inr: float,
        description: str,
        customer_name: str = None,
        customer_email: str = None,
        customer_phone: str = None,
    ) -> dict:
        """Create a Razorpay payment link."""
        if self.simulated:
            link_id = f"plink_sim_{abs(hash(description)) % 100000}"
            return {
                "id": link_id,
                "short_url": f"https://rzp.io/i/{link_id[-8:]}",
                "status": "created",
                "simulated": True,
                "amount": int(amount_inr * 100),
            }
        try:
            data = {
                "amount": int(amount_inr * 100),
                "currency": "INR",
                "description": description,
            }
            if customer_name or customer_email or customer_phone:
                data["customer"] = {}
                if customer_name:
                    data["customer"]["name"] = customer_name
                if customer_email:
                    data["customer"]["email"] = customer_email
                if customer_phone:
                    data["customer"]["contact"] = customer_phone
            result = self.client.payment_link.create(data)
            return result
        except Exception as e:
            logger.error(f"create_payment_link failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ─── Settlements ───

    def fetch_settlements(self) -> list[dict]:
        """Fetch all settlements."""
        if self.simulated:
            data = self._load_synthetic()
            return data.get("settlements") or self._fallback_settlements()
        try:
            settlements = self.client.settlement.all({'count': 100})
            return settlements.get('items', settlements) if isinstance(settlements, dict) else settlements
        except Exception as e:
            logger.error(f"fetch_settlements failed: {e}")
            return []

    # ─── Helpers ───

    def _refund_older_than(self, refund: dict, cutoff) -> bool:
        """Check if a refund is older than the cutoff date."""
        created_at = refund.get("created_at")
        if not created_at:
            return True
        try:
            from datetime import datetime, timezone
            refund_date = datetime.fromtimestamp(created_at, tz=timezone.utc)
            return refund_date < cutoff
        except (ValueError, TypeError, OSError):
            return True

    def is_simulated(self) -> bool:
        """Check if client is in simulated mode."""
        return self.simulated

    # ─── Hardcoded fallbacks (if JSON missing) ───

    def _fallback_authorized_payments(self) -> list[dict]:
        return [
            {
                "id": "pay_sim_auth_001",
                "status": "authorized",
                "amount": 1200000,
                "currency": "INR",
                "method": "upi",
                "email": "customer1@example.com",
                "contact": "+919876543210",
                "created_at": 1724371200,
                "description": "Order #ORD-001 — Wireless Headphones",
                "order_id": "order_sim_001",
            },
            {
                "id": "pay_sim_auth_002",
                "status": "authorized",
                "amount": 6500000,
                "currency": "INR",
                "method": "card",
                "email": "customer2@example.com",
                "contact": "+919876543211",
                "created_at": 1724457600,
                "description": "Order #ORD-002 — Premium Electronics Bundle",
                "order_id": "order_sim_002",
            },
        ]

    def _fallback_failed_payments(self) -> list[dict]:
        return [
            {
                "id": "pay_sim_fail_001",
                "status": "failed",
                "amount": 450000,
                "currency": "INR",
                "method": "upi",
                "email": "customer3@example.com",
                "contact": "+919876543212",
                "created_at": 1724544000,
                "error_code": "UPI_S2S_DECLINED",
                "error_description": "UPI transaction declined by remitter bank",
                "description": "Order #ORD-003 — Office Supplies",
                "order_id": "order_sim_003",
            },
            {
                "id": "pay_sim_fail_002",
                "status": "failed",
                "amount": 220000,
                "currency": "INR",
                "method": "upi",
                "email": "customer4@example.com",
                "contact": "+919876543213",
                "created_at": 1724630400,
                "error_code": "INSUFFICIENT_FUNDS",
                "error_description": "Insufficient funds in remitter account",
                "description": "Order #ORD-004 — Phone Case",
                "order_id": "order_sim_004",
            },
            {
                "id": "pay_sim_fail_003",
                "status": "failed",
                "amount": 890000,
                "currency": "INR",
                "method": "card",
                "email": "customer5@example.com",
                "contact": "+919876543214",
                "created_at": 1724716800,
                "error_code": "NETWORK_TIMEOUT",
                "error_description": "Network timeout during authorization",
                "description": "Order #ORD-005 — Smart Watch",
                "order_id": "order_sim_005",
            },
        ]

    def _fallback_created_orders(self) -> list[dict]:
        return [
            {
                "id": "order_sim_006",
                "status": "created",
                "amount": 780000,
                "currency": "INR",
                "receipt": "receipt_006",
                "notes": {
                    "customer_name": "Rahul",
                    "customer_email": "rahul@example.com",
                    "customer_phone": "+919876543215",
                },
                "created_at": 1724803200,
                "amount_paid": 0,
                "amount_due": 780000,
            },
            {
                "id": "order_sim_008",
                "status": "created",
                "amount": 1500000,
                "currency": "INR",
                "receipt": "receipt_008",
                "notes": {
                    "customer_name": "Arjun",
                    "customer_email": "arjun@example.com",
                    "customer_phone": "+919876543216",
                },
                "created_at": 1724976000,
                "amount_paid": 0,
                "amount_due": 1500000,
            },
        ]

    def _fallback_open_disputes(self) -> list[dict]:
        return [
            {
                "id": "disp_sim_001",
                "status": "open",
                "amount": 820000,
                "currency": "INR",
                "payment_id": "pay_sim_captured_001",
                "reason_code": "product_not_received",
                "reason": "Customer claims product was not received",
                "created_at": 1724371200,
                "respond_by": 1727654400,
            },
            {
                "id": "disp_sim_002",
                "status": "open",
                "amount": 4500000,
                "currency": "INR",
                "payment_id": "pay_sim_captured_002",
                "reason_code": "fraud",
                "reason": "Customer claims fraudulent transaction",
                "created_at": 1724457600,
                "respond_by": 1727740800,
            },
        ]

    def _fallback_pending_refunds(self) -> list[dict]:
        return [
            {
                "id": "rfd_sim_001",
                "status": "pending",
                "amount": 300000,
                "currency": "INR",
                "payment_id": "pay_sim_captured_004",
                "created_at": 1723680000,
                "speed": "normal",
                "notes": {"reason": "customer_request", "card_status": "expired"},
            },
            {
                "id": "rfd_sim_002",
                "status": "pending",
                "amount": 1500000,
                "currency": "INR",
                "payment_id": "pay_sim_captured_005",
                "created_at": 1723766400,
                "speed": "normal",
                "notes": {"reason": "product_return", "card_status": "expired"},
            },
        ]

    def _fallback_settlements(self) -> list[dict]:
        return [
            {
                "id": "setl_sim_001",
                "status": "processed",
                "amount": 2340000,
                "currency": "INR",
                "created_at": 1724371200,
            }
        ]
