"""
Engine 5: Checkout Rescuer — detects abandoned checkouts and sends
personalized Hinglish recovery messages with payment links.
"""

import uuid
from datetime import datetime, timezone
from ai.message_gen import generate_recovery_message
from core.audit_logger import log as audit_log
from core.boundary_enforcer import check_action
from core.issue_store import count_recovery_messages
from core.demo_clock import now_utc, client_is_simulated


class CheckoutRescuer:

    engine_name = "checkout_rescuer"

    def __init__(self, razorpay_client, config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = config
        self.scan_run_id = scan_run_id

    def scan(self) -> list[dict]:
        """Fetch created (unpaid) orders with customer contact info."""
        orders = self.razorpay.fetch_created_orders()
        issues = []
        min_amount = self.config.get("min_order_amount_inr", 500)
        delay_minutes = self.config.get("delay_before_recovery_minutes", 30)
        give_up_hours = self.config.get("give_up_after_hours", 24)
        max_messages = self.config.get("max_recovery_messages_per_order", 1)
        clock = now_utc(simulated=client_is_simulated(self.razorpay))
        history_scan_id = self.scan_run_id if client_is_simulated(self.razorpay) else None

        for o in orders:
            amount_inr = o.get("amount", 0) / 100
            if amount_inr < min_amount:
                continue

            notes = o.get("notes", {})
            customer_email = notes.get("customer_email", "")
            customer_phone = notes.get("customer_phone", "")
            customer_name = notes.get("customer_name", "")

            # Only rescue orders that have at least email or phone
            if not customer_email and not customer_phone:
                continue

            created_at = o.get("created_at") or 0
            try:
                created_dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
                age_minutes = (clock - created_dt).total_seconds() / 60.0
            except (ValueError, TypeError, OSError):
                age_minutes = delay_minutes + 1

            # Too fresh — wait before recovery
            if age_minutes < delay_minutes:
                continue
            # Too old — outside recovery window
            if age_minutes > give_up_hours * 60:
                continue

            order_id = o.get("id")
            if count_recovery_messages(order_id, scan_run_id=history_scan_id) >= max_messages:
                continue

            issues.append({
                "order_id": order_id,
                "amount_inr": amount_inr,
                "receipt": o.get("receipt"),
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
                "created_at": created_at,
                "age_minutes": round(age_minutes, 1),
                "amount_due": o.get("amount_due", 0) / 100,
            })

        return issues

    def diagnose(self, issue: dict) -> dict:
        """Score recovery likelihood."""
        has_email = bool(issue.get("customer_email"))
        has_phone = bool(issue.get("customer_phone"))
        amount = issue["amount_inr"]

        if has_email and has_phone:
            score = 0.75
            level = "high"
        elif has_email:
            score = 0.50
            level = "medium"
        else:
            score = 0.30
            level = "low"

        return {
            "recovery_score": score,
            "recovery_level": level,
            "reasoning": f"Customer has email ({has_email}) and phone ({has_phone}). "
                        f"Order amount: ₹{amount:,.0f}. Recovery likelihood: {level}.",
            "action_recommended": "send_recovery_link",
        }

    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Send recovery payment link with personalized message."""
        amount = issue["amount_inr"]
        order_id = issue["order_id"]

        # Log detection
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="detect",
            razorpay_entity_id=order_id,
            issue_type="abandoned_checkout",
            amount_inr=amount,
            human_readable=f"Found abandoned checkout {order_id} (₹{amount:,.0f}) — customer: {issue.get('customer_name', 'unknown')}",
        )

        # Log diagnosis
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="diagnose",
            razorpay_entity_id=order_id,
            issue_type="abandoned_checkout",
            amount_inr=amount,
            ai_reasoning=diagnosis["reasoning"],
            human_readable=f"Recovery score: {diagnosis['recovery_score']:.2f} ({diagnosis['recovery_level'].upper()}) — {diagnosis['reasoning']}",
        )

        # Check boundaries (use "send_recovery" action — no threshold config, just enabled check)
        boundary = check_action("checkout_rescuer", "send_recovery", amount)

        if not boundary.allowed:
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=order_id,
                amount_inr=amount,
                boundary_check=boundary.reason,
                action_taken="escalated",
                human_readable=f"⚠️ Escalated: {boundary.reason}",
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "abandoned_checkout",
                "razorpay_entity_id": order_id,
                "amount_inr": amount,
                "action_taken": "escalated",
                "action_result": "blocked",
                "escalated": True,
                "recovered": False,
            }

        # Execute: create payment link
        description = f"Complete your order {issue.get('receipt', order_id)}"
        link_result = self.razorpay.create_payment_link(
            amount_inr=amount,
            description=description,
            customer_name=issue.get("customer_name"),
            customer_email=issue.get("customer_email"),
            customer_phone=issue.get("customer_phone"),
        )

        link_url = link_result.get("short_url", "N/A")
        simulated = link_result.get("simulated", False)

        # Generate Hinglish recovery message
        customer_data = {
            "name": issue.get("customer_name", "Customer"),
            "phone": issue.get("customer_phone"),
            "email": issue.get("customer_email"),
        }
        order_data = {
            "amount_inr": amount,
            "items": description,
            "order_id": order_id,
        }
        message_result = generate_recovery_message(order_data, customer_data, link_url)
        message_text = message_result.get("message", "")

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="execute",
            razorpay_entity_id=order_id,
            amount_inr=amount,
            action_taken="recovery_link_sent",
            action_result="success" if link_result.get("status") == "created" else "failed",
            razorpay_api_called="POST /payment_links",
            razorpay_api_response=f"status={link_result.get('status')}, url={link_url}" + (" (simulated)" if simulated else ""),
            ai_reasoning=message_text,
            human_readable=f"📤 Recovery link sent to {issue.get('customer_email', 'customer')} — {link_url}" +
                          (f" | Hinglish msg: \"{message_text[:80]}...\"" if message_text else "") +
                          (" [SIMULATED]" if simulated else ""),
        )

        return {
            "issue_id": str(uuid.uuid4()),
            "engine": self.engine_name,
            "issue_type": "abandoned_checkout",
            "razorpay_entity_id": order_id,
            "amount_inr": amount,
            "recovery_score": diagnosis["recovery_score"],
            "action_taken": "recovery_link_sent",
            "action_result": "pending",
            "amount_pending_inr": amount,
            "recovery_link": link_url,
            "recovery_message": message_text,
            "escalated": False,
            "recovered": False,
            "pending": True,
        }

    def run(self) -> dict:
        if not self.config.get("enabled", False):
            return {"engine": self.engine_name, "scanned": 0, "issues_found": 0, "skipped": True}

        issues = self.scan()
        results = []
        pending = 0
        escalated = 0

        for issue in issues:
            diagnosis = self.diagnose(issue)
            outcome = self.execute(issue, diagnosis)
            results.append(outcome)
            if outcome.get("pending"):
                pending += outcome.get("amount_pending_inr", 0)
            if outcome.get("escalated"):
                escalated += 1

        return {
            "engine": self.engine_name,
            "scanned": len(issues),
            "issues_found": len(issues),
            "amount_pending_inr": pending,
            "escalated": escalated,
            "issues": results,
        }
