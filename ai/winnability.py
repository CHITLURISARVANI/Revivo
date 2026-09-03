"""
AI Winnability Scorer — scores how winnable a dispute is based on evidence.
Uses LLM when available, falls back to rules-based scoring.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

WINNABILITY_SYSTEM_PROMPT = """You are a payment dispute analyst for Indian e-commerce.
Score how winnable a chargeback dispute is based on the available evidence.

Consider:
- Dispute reason (product_not_received, fraud, service_not_as_described, etc.)
- Available evidence (tracking number, delivery confirmation, communication logs, recurring payment patterns)
- Amount at stake

Score from 0.0 to 1.0:
- 0.8+ = strong case, auto-contest recommended
- 0.6-0.8 = moderate case, contest recommended but flag risk factors
- 0.4-0.6 = weak case, escalate to human
- Below 0.4 = very weak, likely lost

Return JSON:
{
    "winnability_score": 0.0-1.0,
    "confidence": "high" | "medium" | "low",
    "recommendation": "contest" | "escalate" | "accept",
    "reasoning": "explanation",
    "evidence_strength": "strong" | "moderate" | "weak",
    "risk_factors": ["list of risk factors"]
}"""


_winnability_cache: dict = {}


def score_dispute_winnability(dispute_data: dict, api_key: str = None) -> dict:
    """
    Score how winnable a dispute is.

    Args:
        dispute_data: dict with dispute reason, amount, payment metadata, available evidence
        api_key: OpenAI API key

    Returns:
        dict with winnability_score, recommendation, reasoning
    """
    cache_key = (
        dispute_data.get("reason_code", dispute_data.get("dispute_reason", dispute_data.get("reason", ""))),
        bool(dispute_data.get("available_evidence", {}).get("has_tracking_number")),
    )
    if cache_key in _winnability_cache:
        return _winnability_cache[cache_key].copy()

    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        try:
            result = _score_with_llm(dispute_data, key)
            _winnability_cache[cache_key] = result
            return result
        except Exception as e:
            logger.warning(f"LLM winnability scoring failed, using fallback: {e}")

    result = _score_with_rules(dispute_data)
    _winnability_cache[cache_key] = result
    return result


def _score_with_llm(dispute_data: dict, api_key: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    context = json.dumps(dispute_data, indent=2)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": WINNABILITY_SYSTEM_PROMPT},
            {"role": "user", "content": f"Score this dispute:\n\n{context}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    result.setdefault("winnability_score", 0.5)
    result.setdefault("confidence", "medium")
    result.setdefault("recommendation", "escalate")
    result.setdefault("reasoning", "LLM scoring")
    result.setdefault("evidence_strength", "moderate")
    result.setdefault("risk_factors", [])
    return result


def _score_with_rules(dispute_data: dict) -> dict:
    """Rules-based winnability scoring."""
    reason = (dispute_data.get("reason_code") or dispute_data.get("dispute_reason") or dispute_data.get("reason") or "").lower()
    evidence = dispute_data.get("available_evidence", {}) or {}
    has_tracking = bool(
        evidence.get("has_tracking_number")
        or dispute_data.get("has_tracking_number")
        or dispute_data.get("tracking_number")
    )
    is_recurring = bool(
        evidence.get("is_recurring_payment")
        or dispute_data.get("is_recurring_payment")
    )
    has_comms = bool(
        evidence.get("has_communication_log")
        or dispute_data.get("has_communication_log")
    )

    # product_not_received + has tracking = strong case
    if "product_not_received" in reason and has_tracking:
        return {
            "winnability_score": 0.82,
            "confidence": "high",
            "recommendation": "contest",
            "reasoning": "Dispute reason is 'product not received' but delivery evidence shows "
                        "tracking number with delivery confirmation. This directly contradicts "
                        "the customer's claim. Strong evidence for contesting.",
            "evidence_strength": "strong",
            "risk_factors": ["No communication log on file"] if not has_comms else [],
        }

    # fraud = always escalate
    if "fraud" in reason:
        return {
            "winnability_score": 0.35,
            "confidence": "low",
            "recommendation": "escalate",
            "reasoning": "Fraud disputes require careful investigation. Cannot auto-contest. "
                        "Needs human review of transaction patterns, IP addresses, and device fingerprints.",
            "evidence_strength": "weak",
            "risk_factors": ["Fraud category requires human judgment", "Potential legal exposure"],
        }

    # service_not_as_described = moderate risk
    if "service_not_as_described" in reason or "not_as_described" in reason:
        if has_tracking:
            return {
                "winnability_score": 0.55,
                "confidence": "medium",
                "recommendation": "escalate",
                "reasoning": "Service not as described disputes are subjective. Delivery proof "
                            "helps but doesn't fully address the claim. Human review needed.",
                "evidence_strength": "moderate",
                "risk_factors": ["Subjective claim", "Delivery proof doesn't address service quality"],
            }
        return {
            "winnability_score": 0.30,
            "confidence": "low",
            "recommendation": "escalate",
            "reasoning": "Service not as described with no delivery proof. Weak case. Escalate.",
            "evidence_strength": "weak",
            "risk_factors": ["No delivery proof", "Subjective claim"],
        }

    # Default: ambiguous
    return {
        "winnability_score": 0.50,
        "confidence": "low",
        "recommendation": "escalate",
        "reasoning": f"Unknown dispute reason '{reason}'. Cannot score with confidence. Escalate.",
        "evidence_strength": "unknown",
        "risk_factors": ["Unknown dispute category"],
    }
