#!/usr/bin/env python3
"""
Seed synthetic test data for Revivo demo.

- Always writes/refreshes data/synthetic_payments.json (50 entities, all 5 leak types)
- If RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET are set, also creates sample
  orders/payments via Razorpay Test Mode where the API allows it.

Usage:
    python scripts/seed_test_data.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "data" / "synthetic_payments.json"

# Deterministic reference time (must match core.demo_clock.FIXED_NOW)
FIXED_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def build_dataset(now: datetime | None = None) -> dict:
    """Build the same synthetic dataset every time (no wall-clock drift)."""
    now = now or FIXED_NOW
    base = int((now - timedelta(days=2)).timestamp())

    payments = []
    for i in range(1, 36):
        payments.append({
            "id": f"pay_sim_cap_{i:03d}",
            "status": "captured",
            "amount": (500 + i * 100) * 100,
            "currency": "INR",
            "method": "upi" if i % 2 else "card",
            "email": f"customer{i}@example.com",
            "contact": f"+91987654{i:04d}",
            "created_at": base + i * 3600,
            "description": f"Order #ORD-{i:03d}",
            "order_id": f"order_sim_cap_{i:03d}",
            "leak_type": None,
        })

    for i, amt in enumerate([12000, 65000, 8500, 3200, 41000], 1):
        payments.append({
            "id": f"pay_sim_auth_{i:03d}",
            "status": "authorized",
            "amount": amt * 100,
            "currency": "INR",
            "method": "upi" if i % 2 else "card",
            "email": f"auth{i}@example.com",
            "contact": f"+91987000{i:04d}",
            "created_at": int((now - timedelta(hours=8 + i)).timestamp()),
            "description": f"Authorized Order #AUTH-{i:03d}",
            "order_id": f"order_sim_auth_{i:03d}",
            "leak_type": "authorized_not_captured",
        })

    failed = [
        ("UPI_S2S_DECLINED", "UPI transaction declined by remitter bank", 4500),
        ("INSUFFICIENT_FUNDS", "Insufficient funds in remitter account", 2200),
        ("NETWORK_TIMEOUT", "Network timeout during authorization", 8900),
        ("INVALID_CARD", "Card number is invalid", 1500),
    ]
    for i, (code, desc, amt) in enumerate(failed, 1):
        payments.append({
            "id": f"pay_sim_fail_{i:03d}",
            "status": "failed",
            "amount": amt * 100,
            "currency": "INR",
            "method": "upi" if i < 3 else "card",
            "email": f"fail{i}@example.com",
            "contact": f"+91987100{i:04d}",
            "created_at": int((now - timedelta(hours=i)).timestamp()),
            "error_code": code,
            "error_description": desc,
            "description": f"Failed Order #FAIL-{i:03d}",
            "order_id": f"order_sim_fail_{i:03d}",
            "leak_type": "failed_payment",
        })

    orders = [
        {
            "id": "order_sim_abandon_001",
            "status": "created",
            "amount": 780000,
            "currency": "INR",
            "receipt": "receipt_abandon_001",
            "notes": {
                "customer_name": "Rahul",
                "customer_email": "rahul@example.com",
                "customer_phone": "+919876543215",
                "items": "Wireless Headphones",
            },
            "created_at": int((now - timedelta(hours=2)).timestamp()),
            "amount_paid": 0,
            "amount_due": 780000,
            "leak_type": "abandoned_checkout",
        },
        {
            "id": "order_sim_abandon_002",
            "status": "created",
            "amount": 1500000,
            "currency": "INR",
            "receipt": "receipt_abandon_002",
            "notes": {
                "customer_name": "Arjun",
                "customer_email": "arjun@example.com",
                "customer_phone": "+919876543216",
                "items": "Smart Watch",
            },
            "created_at": int((now - timedelta(hours=1)).timestamp()),
            "amount_paid": 0,
            "amount_due": 1500000,
            "leak_type": "abandoned_checkout",
        },
    ]

    disputes = [
        {
            "id": "disp_sim_001",
            "status": "open",
            "amount": 820000,
            "currency": "INR",
            "payment_id": "pay_sim_cap_010",
            "reason_code": "product_not_received",
            "reason": "Customer claims product was not received",
            "created_at": int((now - timedelta(days=5)).timestamp()),
            "respond_by": int((now + timedelta(days=30)).timestamp()),
            "leak_type": "uncontested_dispute",
        },
        {
            "id": "disp_sim_002",
            "status": "open",
            "amount": 4500000,
            "currency": "INR",
            "payment_id": "pay_sim_cap_011",
            "reason_code": "fraud",
            "reason": "Customer claims fraudulent transaction",
            "created_at": int((now - timedelta(days=3)).timestamp()),
            "respond_by": int((now + timedelta(days=32)).timestamp()),
            "leak_type": "uncontested_dispute",
        },
    ]

    refunds = [
        {
            "id": "rfd_sim_001",
            "status": "pending",
            "amount": 300000,
            "currency": "INR",
            "payment_id": "pay_sim_cap_012",
            "created_at": int((now - timedelta(days=12)).timestamp()),
            "speed": "normal",
            "notes": {"reason": "customer_request", "card_status": "expired"},
            "leak_type": "stuck_refund",
        },
        {
            "id": "rfd_sim_002",
            "status": "pending",
            "amount": 1500000,
            "currency": "INR",
            "payment_id": "pay_sim_cap_013",
            "created_at": int((now - timedelta(days=10)).timestamp()),
            "speed": "normal",
            "notes": {"reason": "product_return", "card_status": "expired"},
            "leak_type": "stuck_refund",
        },
    ]

    return {
        "meta": {
            "description": "50 synthetic Razorpay entities covering all 5 leak types",
            "generated_at": now.isoformat(),
            "distribution": {
                "captured": 35,
                "authorized": 5,
                "failed": 4,
                "disputes": 2,
                "refunds": 2,
                "abandoned_orders": 2,
                "total_entities": 50,
            },
        },
        "payments": payments,
        "orders": orders,
        "disputes": disputes,
        "refunds": refunds,
        "settlements": [
            {
                "id": "setl_sim_001",
                "status": "processed",
                "amount": 2340000,
                "currency": "INR",
                "created_at": base,
            }
        ],
    }


def write_json(dataset: dict) -> Path:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    return DATA_PATH


def seed_razorpay_test_mode(dataset: dict) -> dict:
    """
    Best-effort seed into Razorpay Test Mode.
    Creates unpaid orders (abandoned checkout targets). Payments/disputes/refunds
    with leak states cannot be fully fabricated via API — JSON remains source of truth.
    """
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        return {"mode": "json_only", "created_orders": []}

    try:
        import razorpay
    except ImportError:
        return {"mode": "json_only", "error": "razorpay package not installed"}

    client = razorpay.Client(auth=(key_id, key_secret))
    created = []
    for order in dataset["orders"]:
        try:
            result = client.order.create({
                "amount": order["amount"],
                "currency": order["currency"],
                "receipt": order["receipt"],
                "notes": order.get("notes", {}),
            })
            created.append(result.get("id"))
            print(f"  Created Razorpay order {result.get('id')}")
        except Exception as e:
            print(f"  Failed to create order {order['id']}: {e}")

    return {"mode": "razorpay_test", "created_orders": created}


def main():
    print("Revivo — Synthetic Test Data Seeder")
    print("=" * 50)

    dataset = build_dataset()
    path = write_json(dataset)
    dist = dataset["meta"]["distribution"]

    print(f"Wrote {path}")
    print(f"  Payments:  {len(dataset['payments'])} "
          f"(captured={dist['captured']}, authorized={dist['authorized']}, failed={dist['failed']})")
    print(f"  Orders:    {len(dataset['orders'])} abandoned")
    print(f"  Disputes:  {len(dataset['disputes'])} open")
    print(f"  Refunds:   {len(dataset['refunds'])} pending")
    print(f"  Total:     {dist['total_entities']} entities")
    print()

    result = seed_razorpay_test_mode(dataset)
    if result["mode"] == "json_only":
        print("No Razorpay keys — demo will use data/synthetic_payments.json (simulated mode).")
        print("Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET to also create test-mode orders.")
    else:
        print(f"Razorpay test mode: created {len(result.get('created_orders', []))} orders.")

    print()
    print("Done. Run: python demo.py")


if __name__ == "__main__":
    main()
