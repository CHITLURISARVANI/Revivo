"""
Engine 2: Retry Strategist — detects failed payments, classifies them with AI
as transient/permanent/ambiguous, and sends retry payment links for transient ones.
"""

import uuid
from ai.classifier import classify_failure
from ai.message_gen import generate_recovery_message
from core.audit_logger import log as audit_log
from core.boundary_enforcer import check_action
from core.issue_store import get_retry_history
from core.demo_clock import client_is_simulated


class RetryStrategist:

    engine_name = "retry_strategist"

    def __init__(self, razorpay_client, config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = config
        self.scan_run_id = scan_run_id

    def scan(self) -> list[dict]:
        """Fetch failed payments from the last 24 hours."""
        payments = self.razorpay.fetch_failed_payments(hours=24)
        issues = []
        for p in payments:
            amount_inr = p.get("amount", 0) / 100
            issues.append({
                "payment_id": p.get("id"),
                "amount_inr": amount_inr,
                "method": p.get("method"),
                "email": p.get("email"),
                "contact": p.get("contact"),
                "error_code": p.get("error_code"),
                "error_description": p.get("error_description"),
                "description": p.get("description"),
                "order_id": p.get("order_id"),
                "created_at": p.get("created_at"),
            })
        return issues

    def diagnose(self, issue: dict) -> dict:
        """Classify the failure using AI (or rules-based fallback)."""
        payment_data = {
            "payment_id": issue["payment_id"],
            "error_code": issue.get("error_code", ""),
            "error_description": issue.get("error_description", ""),
            "payment_method": issue.get("method", ""),
            "amount": issue["amount_inr"],
            "currency": "INR",
        }
        return classify_failure(payment_data)

    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Send retry link if transient and within bounds, or escalate."""
        amount = issue["amount_inr"]
        payment_id = issue["payment_id"]

        # Log detection
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="detect",
            razorpay_entity_id=payment_id,
            issue_type="failed_payment",
            amount_inr=amount,
            human_readable=f"Found failed payment {payment_id} (₹{amount:,.0f}) — error: {issue.get('error_code', 'unknown')}",
        )

        # Log diagnosis
        classification = diagnosis.get("classification", "ambiguous")
        confidence = diagnosis.get("confidence", 0)
        reasoning = diagnosis.get("reasoning", "")

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="diagnose",
            razorpay_entity_id=payment_id,
            issue_type="failed_payment",
            amount_inr=amount,
            ai_reasoning=reasoning,
            human_readable=f"AI classification: {classification.upper()} (confidence: {confidence:.0%}) — {reasoning}",
        )

        # If permanent or ambiguous — don't retry
        if classification != "transient":
            action = "no_retry" if classification == "permanent" else "escalated"
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=payment_id,
                amount_inr=amount,
                action_taken=action,
                boundary_check="within_bounds",
                human_readable=f"{'✋ No retry — permanent failure' if classification == 'permanent' else '📋 Escalated — ambiguous failure'}",
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "failed_payment",
                "razorpay_entity_id": payment_id,
                "amount_inr": amount,
                "ai_classification": classification,
                "ai_confidence": confidence,
                "ai_reasoning": reasoning,
                "action_taken": action,
                "action_result": "no_action" if classification == "permanent" else "escalated",
                "escalated": classification == "ambiguous",
                "recovered": False,
            }

        # Check boundaries for retry (max 2 + 30-min gap)
        # Simulated mode: only count retries inside THIS scan so repeated scans
        # on the same seed stay identical (server-side shared DB, idempotent demo).
        history_scan_id = self.scan_run_id if client_is_simulated(self.razorpay) else None
        history = get_retry_history(payment_id, scan_run_id=history_scan_id)
        retry_count = history["retry_count"]
        minutes_since = history["minutes_since_last_retry"]
        boundary = check_action(
            "retry_strategist",
            "retry",
            amount,
            retry_count=retry_count,
            minutes_since_last_retry=minutes_since,
        )

        if not boundary.allowed:
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=payment_id,
                amount_inr=amount,
                boundary_check=boundary.reason,
                action_taken="escalated" if boundary.escalate else "blocked",
                human_readable=f"⚠️ {'Escalated' if boundary.escalate else 'Blocked'}: {boundary.reason}"
                + (f" (retries={retry_count})" if retry_count else ""),
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "failed_payment",
                "razorpay_entity_id": payment_id,
                "amount_inr": amount,
                "ai_classification": classification,
                "ai_confidence": confidence,
                "ai_reasoning": reasoning,
                "action_taken": "escalated" if boundary.escalate else "blocked",
                "action_result": "blocked",
                "retry_count": retry_count,
                "escalated": bool(boundary.escalate),
                "recovered": False,
            }

        # Execute: create payment link for retry
        description = issue.get("description", f"Retry payment for {payment_id}")
        link_result = self.razorpay.create_payment_link(
            amount_inr=amount,
            description=f"Retry: {description}",
            customer_email=issue.get("email"),
            customer_phone=issue.get("contact"),
        )

        link_url = link_result.get("short_url", "N/A")
        simulated = link_result.get("simulated", False)

        # Generate Hinglish recovery message
        customer_data = {"name": "Customer", "phone": issue.get("contact"), "email": issue.get("email")}
        order_data = {"amount_inr": amount, "items": description}
        message_result = generate_recovery_message(order_data, customer_data, link_url)

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="execute",
            razorpay_entity_id=payment_id,
            amount_inr=amount,
            action_taken="retry_link_sent",
            action_result="success" if link_result.get("status") == "created" else "failed",
            razorpay_api_called="POST /payment_links",
            razorpay_api_response=f"status={link_result.get('status')}, url={link_url}" + (" (simulated)" if simulated else ""),
            ai_reasoning=message_result.get("message", ""),
            human_readable=f"📤 Retry link sent to {issue.get('email', 'customer')} — {link_url}" +
                          (f" | Message: \"{message_result.get('message', '')[:80]}...\"" if message_result.get("message") else "") +
                          (" [SIMULATED]" if simulated else ""),
        )

        return {
            "issue_id": str(uuid.uuid4()),
            "engine": self.engine_name,
            "issue_type": "failed_payment",
            "razorpay_entity_id": payment_id,
            "amount_inr": amount,
            "ai_classification": classification,
            "ai_confidence": confidence,
            "ai_reasoning": reasoning,
            "action_taken": "retry_link_sent",
            "action_result": "pending",
            "amount_pending_inr": amount,
            "recovery_link": link_url,
            "recovery_message": message_result.get("message", ""),
            "retry_count": retry_count + 1,
            "escalated": False,
            "recovered": False,
            "pending": True,
        }

    def run(self) -> dict:
        """Run the full engine cycle."""
        if not self.config.get("enabled", False):
            return {"engine": self.engine_name, "scanned": 0, "issues_found": 0, "skipped": True}

        issues = self.scan()
        results = []
        recovered = 0
        pending = 0
        escalated = 0

        for issue in issues:
            diagnosis = self.diagnose(issue)
            outcome = self.execute(issue, diagnosis)
            results.append(outcome)
            if outcome.get("recovered"):
                recovered += outcome.get("amount_recovered_inr", 0)
            if outcome.get("pending"):
                pending += outcome.get("amount_pending_inr", 0)
            if outcome.get("escalated"):
                escalated += 1

        return {
            "engine": self.engine_name,
            "scanned": len(issues),
            "issues_found": len(issues),
            "amount_recovered_inr": recovered,
            "amount_pending_inr": pending,
            "escalated": escalated,
            "issues": results,
        }
