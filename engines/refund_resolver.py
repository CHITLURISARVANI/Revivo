"""
Engine 4: Refund Resolver — detects stuck refunds, diagnoses the cause,
and reissues as instant refunds within merchant-set bounds.
"""

import uuid
import json
from core.audit_logger import log as audit_log
from core.boundary_enforcer import check_action


class RefundResolver:

    engine_name = "refund_resolver"

    def __init__(self, razorpay_client, config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = config
        self.scan_run_id = scan_run_id

    def scan(self) -> list[dict]:
        """Fetch pending refunds older than the configured threshold."""
        min_age_days = self.config.get("min_pending_age_days", 7)
        refunds = self.razorpay.fetch_pending_refunds(days=min_age_days)
        issues = []
        for r in refunds:
            amount_inr = r.get("amount", 0) / 100
            notes = r.get("notes", {})
            issues.append({
                "refund_id": r.get("id"),
                "amount_inr": amount_inr,
                "payment_id": r.get("payment_id"),
                "status": r.get("status"),
                "speed": r.get("speed"),
                "created_at": r.get("created_at"),
                "notes": notes,
                "card_status": notes.get("card_status", "unknown"),
            })
        return issues

    def diagnose(self, issue: dict) -> dict:
        """Diagnose why the refund is stuck."""
        card_status = issue.get("card_status", "unknown")

        if card_status == "expired":
            return {
                "diagnosis": "card_expired",
                "reason": "Customer's card has expired. Normal refund cannot process. "
                         "Reissue as instant refund to customer's bank account.",
                "action_recommended": "instant_refund",
            }

        if card_status == "closed":
            return {
                "diagnosis": "account_closed",
                "reason": "Customer's bank account appears to be closed. "
                         "Cannot auto-reissue. Customer needs to provide new account details.",
                "action_recommended": "escalate",
            }

        return {
            "diagnosis": "processing_delay",
            "reason": f"Refund has been pending for an extended period. "
                     f"Likely a processing delay on the acquiring bank's side.",
            "action_recommended": "wait",
        }

    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Reissue refund or escalate based on diagnosis."""
        amount = issue["amount_inr"]
        refund_id = issue["refund_id"]
        payment_id = issue["payment_id"]
        action = diagnosis.get("action_recommended", "wait")

        # Log detection
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="detect",
            razorpay_entity_id=refund_id,
            issue_type="stuck_refund",
            amount_inr=amount,
            human_readable=f"Found stuck refund {refund_id} (₹{amount:,.0f}) — status: pending, card: {issue.get('card_status', 'unknown')}",
        )

        # Log diagnosis
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="diagnose",
            razorpay_entity_id=refund_id,
            issue_type="stuck_refund",
            amount_inr=amount,
            ai_reasoning=diagnosis["reason"],
            human_readable=f"Diagnosis: {diagnosis['diagnosis']} — {diagnosis['reason']}",
        )

        # If not instant_refund, escalate or wait
        if action == "escalate":
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=refund_id,
                amount_inr=amount,
                action_taken="escalated",
                human_readable=f"📋 Escalated: {diagnosis['diagnosis']}",
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "stuck_refund",
                "razorpay_entity_id": refund_id,
                "amount_inr": amount,
                "diagnosis": diagnosis["diagnosis"],
                "action_taken": "escalated",
                "action_result": "escalated",
                "escalated": True,
                "recovered": False,
            }

        if action == "wait":
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=refund_id,
                amount_inr=amount,
                action_taken="waiting",
                human_readable=f"⏳ Waiting — processing delay, will re-check next scan",
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "stuck_refund",
                "razorpay_entity_id": refund_id,
                "amount_inr": amount,
                "diagnosis": diagnosis["diagnosis"],
                "action_taken": "waiting",
                "action_result": "pending",
                "escalated": False,
                "recovered": False,
            }

        # Check boundaries for instant refund
        boundary = check_action("refund_resolver", "auto_reissue", amount)

        if not boundary.allowed:
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=refund_id,
                amount_inr=amount,
                boundary_check=boundary.reason,
                action_taken="escalated",
                human_readable=f"⚠️ ESCALATED: {boundary.reason}" +
                              (f" (₹{amount:,.0f} > ₹{boundary.threshold:,.0f})" if boundary.threshold else ""),
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "stuck_refund",
                "razorpay_entity_id": refund_id,
                "amount_inr": amount,
                "diagnosis": diagnosis["diagnosis"],
                "action_taken": "escalated",
                "action_result": "blocked",
                "escalated": True,
                "recovered": False,
            }

        # Execute: create instant refund
        result = self.razorpay.create_instant_refund(payment_id, amount)
        processed = result.get("status") == "processed" or result.get("simulated", False)
        simulated = result.get("simulated", False)

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="execute",
            razorpay_entity_id=refund_id,
            amount_inr=amount,
            action_taken="instant_refund_issued",
            action_result="success" if processed else "failed",
            amount_recovered_inr=amount if processed else 0,
            razorpay_api_called=f"POST /refunds (instant) for payment {payment_id}",
            razorpay_api_response=f"status={result.get('status')}" + (" (simulated)" if simulated else ""),
            human_readable=f"✅ Reissued instant refund for {refund_id} (₹{amount:,.0f}) — customer's card was expired." +
                          (" [SIMULATED]" if simulated else ""),
        )

        return {
            "issue_id": str(uuid.uuid4()),
            "engine": self.engine_name,
            "issue_type": "stuck_refund",
            "razorpay_entity_id": refund_id,
            "amount_inr": amount,
            "diagnosis": diagnosis["diagnosis"],
            "action_taken": "instant_refund_issued",
            "action_result": "success" if processed else "failed",
            "amount_recovered_inr": amount if processed else 0,
            "recovered": processed,
            "escalated": False,
        }

    def run(self) -> dict:
        if not self.config.get("enabled", False):
            return {"engine": self.engine_name, "scanned": 0, "issues_found": 0, "skipped": True}

        issues = self.scan()
        results = []
        recovered = 0
        escalated = 0

        for issue in issues:
            diagnosis = self.diagnose(issue)
            outcome = self.execute(issue, diagnosis)
            results.append(outcome)
            if outcome.get("recovered"):
                recovered += outcome.get("amount_recovered_inr", 0)
            if outcome.get("escalated"):
                escalated += 1

        return {
            "engine": self.engine_name,
            "scanned": len(issues),
            "issues_found": len(issues),
            "amount_recovered_inr": recovered,
            "escalated": escalated,
            "issues": results,
        }
