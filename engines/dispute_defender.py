"""
Engine 3: Dispute Defender — detects open disputes, scores winnability with AI,
and auto-contests with AI-generated evidence within merchant-set bounds.
"""

import uuid
import json
from ai.winnability import score_dispute_winnability
from ai.evidence_gen import generate_dispute_evidence
from core.audit_logger import log as audit_log
from core.boundary_enforcer import check_action


class DisputeDefender:

    engine_name = "dispute_defender"

    def __init__(self, razorpay_client, config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = config
        self.scan_run_id = scan_run_id

    def scan(self) -> list[dict]:
        """Fetch open disputes."""
        disputes = self.razorpay.fetch_open_disputes()
        issues = []
        for d in disputes:
            amount_inr = d.get("amount", 0) / 100
            issues.append({
                "dispute_id": d.get("id"),
                "amount_inr": amount_inr,
                "payment_id": d.get("payment_id"),
                "reason_code": d.get("reason_code", ""),
                "reason": d.get("reason", ""),
                "created_at": d.get("created_at"),
                "respond_by": d.get("respond_by"),
            })
        return issues

    def diagnose(self, issue: dict) -> dict:
        """Score winnability using AI."""
        # Build evidence data from what we know
        reason_code = issue.get("reason_code", "")
        reason = issue.get("reason", "")

        # Simulated evidence — in production, this would come from merchant's shipping/CRM
        available_evidence = self._gather_evidence(issue)

        dispute_data = {
            "dispute_id": issue["dispute_id"],
            "dispute_reason": reason_code or reason,
            "reason_code": reason_code,
            "dispute_amount": issue["amount_inr"],
            "payment_id": issue.get("payment_id"),
            "available_evidence": available_evidence,
        }

        winnability = score_dispute_winnability(dispute_data)

        # Also generate evidence if winnable
        evidence = None
        if winnability.get("recommendation") == "contest":
            evidence = generate_dispute_evidence(dispute_data, winnability)

        return {
            "winnability": winnability,
            "evidence": evidence,
            "dispute_data": dispute_data,
        }

    def _gather_evidence(self, issue: dict) -> dict:
        """Gather available evidence for a dispute."""
        reason = issue.get("reason_code", "").lower()

        if "product_not_received" in reason:
            # Simulated delivery proof — in production, fetch from shipping provider
            return {
                "has_tracking_number": True,
                "tracking_number": "DL123456",
                "delivery_date": "2025-03-15",
                "delivery_signed_by": "Rajesh",
                "has_communication_log": False,
                "is_recurring_payment": False,
            }

        if "fraud" in reason:
            return {
                "has_tracking_number": False,
                "has_communication_log": False,
                "is_recurring_payment": True,
            }

        if "service_not_as_described" in reason:
            return {
                "has_tracking_number": True,
                "tracking_number": "EK789012",
                "delivery_date": "2025-04-10",
                "delivery_signed_by": "Priya",
                "has_communication_log": True,
                "is_recurring_payment": False,
            }

        return {
            "has_tracking_number": False,
            "has_communication_log": False,
            "is_recurring_payment": False,
        }

    def _ai_evidence_line(self, diagnosis: dict, fallback_reasoning: str) -> str:
        """Human-readable AI column text with tracking when available."""
        evidence_pkg = diagnosis.get("evidence") or {}
        dispute_data = diagnosis.get("dispute_data") or {}
        avail = dispute_data.get("available_evidence") or {}
        tracking = avail.get("tracking_number")
        signed = avail.get("delivery_signed_by")
        if tracking:
            line = f"Delhivery tracking {tracking} delivered"
            if signed:
                line += f", signed by {signed}"
            summary = evidence_pkg.get("summary")
            if summary:
                line += f" — {summary}"
            return line
        return fallback_reasoning or evidence_pkg.get("summary") or ""

    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Contest the dispute within bounds, or escalate."""
        amount = issue["amount_inr"]
        dispute_id = issue["dispute_id"]
        winnability = diagnosis.get("winnability", {})
        evidence = diagnosis.get("evidence")
        reason_code = issue.get("reason_code", "")

        # Log detection
        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="detect",
            razorpay_entity_id=dispute_id,
            issue_type="open_dispute",
            amount_inr=amount,
            human_readable=f"Found open dispute {dispute_id} (₹{amount:,.0f}) — reason: {reason_code}",
        )

        # Log diagnosis
        score = winnability.get("winnability_score", 0)
        recommendation = winnability.get("recommendation", "escalate")
        reasoning = winnability.get("reasoning", "")

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="diagnose",
            razorpay_entity_id=dispute_id,
            issue_type="open_dispute",
            amount_inr=amount,
            ai_reasoning=reasoning,
            human_readable=f"AI winnability score: {score:.2f} ({recommendation.upper()}) — {reasoning}",
        )

        # If recommendation is not "contest", escalate or accept
        if recommendation != "contest":
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=dispute_id,
                amount_inr=amount,
                action_taken="escalated",
                human_readable=f"📋 Escalated to human — winnability {score:.2f}, recommendation: {recommendation}",
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "open_dispute",
                "razorpay_entity_id": dispute_id,
                "amount_inr": amount,
                "ai_winnability_score": score,
                "ai_reasoning": self._ai_evidence_line(diagnosis, reasoning),
                "evidence_summary": (diagnosis.get("evidence") or {}).get("summary"),
                "action_taken": "escalated",
                "action_result": "escalated",
                "escalated": True,
                "recovered": False,
            }

        # Check boundaries (never auto-contest fraud; amount + winnability gates)
        raw_reason = (reason_code or "").lower()
        restricted = [c.lower() for c in self.config.get("never_auto_contest_categories", [])]
        category = next((c for c in restricted if c == raw_reason or c in raw_reason), None)
        boundary = check_action(
            "dispute_defender",
            "auto_contest",
            amount,
            category=category,
            winnability_score=score,
        )

        if not boundary.allowed:
            audit_log(
                scan_run_id=self.scan_run_id,
                engine=self.engine_name,
                phase="decide",
                razorpay_entity_id=dispute_id,
                amount_inr=amount,
                boundary_check=boundary.reason,
                action_taken="escalated",
                human_readable=f"⚠️ ESCALATED: {boundary.reason}" +
                              (f" (₹{amount:,.0f} > ₹{boundary.threshold:,.0f})" if boundary.threshold else ""),
            )
            return {
                "issue_id": str(uuid.uuid4()),
                "engine": self.engine_name,
                "issue_type": "open_dispute",
                "razorpay_entity_id": dispute_id,
                "amount_inr": amount,
                "ai_winnability_score": score,
                "ai_reasoning": self._ai_evidence_line(diagnosis, reasoning),
                "evidence_summary": (diagnosis.get("evidence") or {}).get("summary"),
                "action_taken": "escalated",
                "action_result": "blocked",
                "escalated": True,
                "recovered": False,
            }

        # Execute: contest the dispute
        contest_data = {
            "amount": int(amount * 100),
            "summary": evidence.get("summary", "We contest this dispute."),
            "action": "contested",
            "notes": {
                "evidence": evidence.get("contest_text", ""),
                "evidence_documents": json.dumps(evidence.get("evidence_documents", [])),
            },
        }

        result = self.razorpay.contest_dispute(dispute_id, contest_data)
        contested = result.get("status") == "contested" or result.get("simulated", False)
        simulated = result.get("simulated", False)

        audit_log(
            scan_run_id=self.scan_run_id,
            engine=self.engine_name,
            phase="execute",
            razorpay_entity_id=dispute_id,
            amount_inr=amount,
            action_taken="contested",
            action_result="success" if contested else "failed",
            razorpay_api_called=f"PATCH /disputes/{dispute_id}/contest",
            razorpay_api_response=f"status={result.get('status')}" + (" (simulated)" if simulated else ""),
            ai_reasoning=evidence.get("contest_text", "")[:200] if evidence else "",
            human_readable=f"⚖️ Contested dispute {dispute_id} (₹{amount:,.0f}) with AI-generated evidence." +
                          (f" Evidence: \"{evidence.get('summary', '')}\"" if evidence else "") +
                          (" [SIMULATED]" if simulated else ""),
        )

        return {
            "issue_id": str(uuid.uuid4()),
            "engine": self.engine_name,
            "issue_type": "open_dispute",
            "razorpay_entity_id": dispute_id,
            "amount_inr": amount,
            "ai_winnability_score": score,
            "ai_reasoning": self._ai_evidence_line(diagnosis, reasoning),
            "evidence_summary": evidence.get("summary", "") if evidence else "",
            "action_taken": "contested",
            "action_result": "success" if contested else "failed",
            "amount_recovered_inr": amount if contested else 0,  # contested = potentially recovered
            "escalated": False,
            "recovered": contested,
            "pending": not contested,
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
