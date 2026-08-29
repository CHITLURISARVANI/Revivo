"""
Engine 1: Capture Guardian — detects authorized-not-captured payments
and auto-captures them within merchant-set bounds.
"""

import uuid
from datetime import datetime, timezone, timedelta
from core.audit_logger import log as audit_log
from core.boundary_enforcer import check_action


class CaptureGuardian:

    engine_name = "capture_guardian"

    def __init__(self, razorpay_client, config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = config
        self.scan_run_id = scan_run_id

    def scan(self) -> list[dict]:
        """Fetch authorized payments and detect ones that are stuck."""
        payments = self.razorpay.fetch_authorized_payments()
        issues = []
        min_age_hours = self.config.get("min_authorized_age_hours", 6)

        for p in payments:
            amount_inr = p.get("amount", 0) / 100  # paise → INR
            created_at = p.get("created_at", 0)

            # Calculate age in hours
            if created_at:
                try:
                    created_dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
                    age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
                except (ValueError, TypeError, OSError):
                    age_hours = min_age_hours + 1  # assume old enough
            else:
                age_hours = min_age_hours + 1  # assume old enough

            if age_hours >= min_age_hours:
                issues.append({
                    "payment_id": p.get("id"),
                    "amount_inr": amount_inr,
                    "method": p.get("method"),
                    "email": p.get("email"),
                    "contact": p.get("contact"),
                    "description": p.get("description"),
                    "order_id": p.get("order_id"),
                    "age_hours": round(age_hours, 1),
                    "created_at": created_at,
                })

        return issues

    def diagnose(self, issue: dict) -> dict:
        """Diagnose why the payment wasn't captured."""
        # For authorized payments, diagnosis is simple — it's stuck
        return {
            "diagnosis": "authorized_not_captured",
            "reason": f"Payment has been in 'authorized' state for {issue['age_hours']}h. "
                     f"Likely webhook delivery failure or merchant oversight.",
            "action_recommended": "capture",
        }

    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Capture the payment within bounds, or escalate."""
        amount = issue["amount_inr"]
        payment_id = issue["payment_id"]

        # Log detection
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="detect",
            razorpay_entity_id=payment_id,
            issue_type="authorized_not_captured",
            amount_inr=amount,
            human_readable=f"Found authorized payment {payment_id} (₹{amount:,.0f}) stuck for {issue['age_hours']}h.",
        )

        # Log diagnosis
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="diagnose",
            razorpay_entity_id=payment_id,
            issue_type="authorized_not_captured",
            amount_inr=amount,
            ai_reasoning=diagnosis["reason"],
            human_readable=f"Diagnosis: {diagnosis['reason']}",
        )

        # Check boundaries
        boundary = check_action("capture_guardian", "auto_capture", amount)

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="decide",
            razorpay_entity_id=payment_id,
            amount_inr=amount,
            boundary_check=boundary.reason,
            human_readable=f"Boundary check: {boundary.reason}" +
                          (f" (₹{amount:,.0f} > ₹{boundary.threshold:,.0f})" if boundary.threshold else ""),
        )

        if not boundary.allowed:
            # Escalate
            escalation = {
                "id": str(uuid.uuid4()),
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "reason": boundary.reason,
                "amount_inr": amount,
                "payment_id": payment_id,
                "escalated": True,
            }
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="escalate",
                razorpay_entity_id=payment_id,
                amount_inr=amount,
                action_taken="escalated",
                action_result="blocked",
                boundary_check=boundary.reason,
                human_readable=f"⚠️ ESCALATED: Payment {payment_id} (₹{amount:,.0f}) — {boundary.reason}. Needs human review.",
            )
            return {
                **escalation,
                "razorpay_entity_id": payment_id,
                "issue_type": "authorized_not_captured",
                "amount_inr": amount,
                "action_taken": "escalated",
                "action_result": "blocked",
            }

        # Execute capture
        result = self.razorpay.capture_payment(payment_id, amount)
        captured = result.get("status") == "captured"
        simulated = result.get("simulated", False)

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="execute",
            razorpay_entity_id=payment_id,
            amount_inr=amount,
            action_taken="captured",
            action_result="success" if captured else "failed",
            amount_recovered_inr=amount if captured else 0,
            razorpay_api_called=f"POST /payments/{payment_id}/capture",
            razorpay_api_response=f"status={result.get('status')}" + (" (simulated)" if simulated else ""),
            human_readable=f"✅ Captured payment {payment_id} (₹{amount:,.0f}) — authorized for {issue['age_hours']}h." +
                          (" [SIMULATED]" if simulated else ""),
        )

        return {
            "issue_id": str(uuid.uuid4()),
            "engine": self.engine_name,
            "issue_type": "authorized_not_captured",
            "razorpay_entity_id": payment_id,
            "amount_inr": amount,
            "action_taken": "captured",
            "action_result": "success" if captured else "failed",
            "amount_recovered_inr": amount if captured else 0,
            "recovered": captured,
            "escalated": False,
        }

    def run(self) -> dict:
        """Run the full engine cycle."""
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
                recovered += outcome["amount_recovered_inr"]
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
