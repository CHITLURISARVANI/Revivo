"""
AI Evidence Generator — generates structured contest evidence for disputes.
Uses LLM when available, falls back to template-based generation.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

EVIDENCE_SYSTEM_PROMPT = """You are a dispute response writer for an Indian e-commerce merchant.
Generate structured evidence to contest a chargeback dispute.

The evidence should:
1. State clearly why the merchant is contesting
2. Reference specific evidence (tracking numbers, delivery dates, signatures)
3. Be professional, factual, and concise
4. Directly address the customer's claim

Return JSON:
{
    "contest_text": "the evidence statement to submit to Razorpay",
    "evidence_documents": [
        {"type": "delivery_proof", "description": "what this evidence proves"}
    ],
    "summary": "one-line summary of the evidence"
}"""


def generate_dispute_evidence(dispute_data: dict, winnability_result: dict, api_key: str = None) -> dict:
    """
    Generate contest evidence for a dispute.

    Args:
        dispute_data: dict with dispute details and available evidence
        winnability_result: result from winnability scorer
        api_key: OpenAI API key

    Returns:
        dict with contest_text, evidence_documents, summary
    """
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        try:
            return _generate_with_llm(dispute_data, winnability_result, key)
        except Exception as e:
            logger.warning(f"LLM evidence generation failed, using fallback: {e}")

    return _generate_with_template(dispute_data, winnability_result)


def _generate_with_llm(dispute_data: dict, winnability_result: dict, api_key: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    context = json.dumps({
        "dispute": dispute_data,
        "winnability_analysis": winnability_result,
    }, indent=2)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EVIDENCE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate contest evidence for this dispute:\n\n{context}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    result.setdefault("contest_text", "We contest this dispute based on available evidence.")
    result.setdefault("evidence_documents", [])
    result.setdefault("summary", "Evidence submitted for dispute contest.")
    return result


def _generate_with_template(dispute_data: dict, winnability_result: dict) -> dict:
    """Template-based evidence generation."""
    reason = (dispute_data.get("reason_code") or dispute_data.get("reason") or "").lower()
    evidence = dispute_data.get("available_evidence", {})
    amount = dispute_data.get("amount", 0) / 100  # paise to INR

    tracking = evidence.get("tracking_number", "N/A")
    delivery_date = evidence.get("delivery_date", "N/A")
    signed_by = evidence.get("delivery_signed_by", "N/A")

    if "product_not_received" in reason and evidence.get("has_tracking_number"):
        contest_text = (
            f"We contest this dispute on the grounds that the product was successfully delivered. "
            f"Tracking number {tracking} confirms delivery on {delivery_date}, "
            f"signed by '{signed_by}' at the customer's address. "
            f"The customer's claim of 'product not received' is directly contradicted by "
            f"verified delivery records from our logistics partner. "
            f"We request the dispute be ruled in our favor."
        )
        return {
            "contest_text": contest_text,
            "evidence_documents": [
                {
                    "type": "delivery_proof",
                    "description": f"Tracking {tracking} — delivery confirmed on {delivery_date}, signed by {signed_by}",
                }
            ],
            "summary": f"Delivery confirmed with tracking {tracking}. Customer claim contradicted by evidence.",
        }

    if "service_not_as_described" in reason:
        contest_text = (
            f"We contest this dispute. The service was delivered as described in our listing. "
            f"Transaction was authorized by the customer and the product/service was provided as agreed. "
            f"We request additional information from the customer specifying what aspect was "
            f"'not as described' so we can address the concern."
        )
        return {
            "contest_text": contest_text,
            "evidence_documents": [],
            "summary": "Service delivered as described. Requesting specific complaint details.",
        }

    # Generic
    contest_text = (
        f"We contest this dispute. The transaction of ₹{amount:,.0f} was legitimately processed "
        f"and authorized by the customer. We have transaction records confirming the payment was valid. "
        f"We request the dispute be ruled in our favor."
    )
    return {
        "contest_text": contest_text,
        "evidence_documents": [],
        "summary": "Transaction was legitimate and customer-authorized.",
    }
