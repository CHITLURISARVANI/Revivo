"""
AI Failure Classifier — classifies payment failures as transient/permanent/ambiguous.
Uses LLM when available, falls back to rules-based classification.
"""

import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── LLM-based classification ───

CLASSIFY_SYSTEM_PROMPT = """You are a payment failure analyst for Indian payment systems.
Classify payment failures into one of three categories:

1. "transient" — caused by infrastructure issues (bank downtime, network timeout, UPI rail degradation, gateway congestion). Retry is recommended because the customer would likely succeed on a second attempt.

2. "permanent" — caused by customer-side issues (insufficient funds, invalid card, expired card, mandate revoked, account closed). Retry is not useful because the same issue will recur.

3. "ambiguous" — cannot determine with available data. Escalate to human.

Consider: error code, error description, payment method, bank name, timestamp, amount, customer history.
Be honest about confidence. If unsure, classify as "ambiguous".

Return JSON:
{
    "classification": "transient" | "permanent" | "ambiguous",
    "confidence": 0.0-1.0,
    "reasoning": "explanation",
    "retry_recommended": true/false,
    "retry_delay_minutes": 30,
    "max_retries": 2
}"""

TRANSIENT_ERROR_CODES = {
    "UPI_S2S_DECLINED", "NETWORK_TIMEOUT", "GATEWAY_ERROR",
    "BANK_DOWNTIME", "UPI_DECLINED", "SERVER_ERROR",
    "CONNECTION_TIMEOUT", "PROCESSOR_ERROR", "RATE_LIMITED",
}

PERMANENT_ERROR_CODES = {
    "INSUFFICIENT_FUNDS", "INVALID_CARD", "CARD_EXPIRED",
    "MANDATE_REVOKED", "ACCOUNT_CLOSED", "AUTHENTICATION_FAILED",
    "CARD_DECLINED", "INSUFFICIENT_BALANCE",
}


_classify_cache: dict = {}


def classify_failure(payment_data: dict, api_key: str = None) -> dict:
    """
    Classify a payment failure.

    Args:
        payment_data: dict with error_code, error_description, method, amount, etc.
        api_key: OpenAI API key. If None, tries env var. If no key, uses fallback.

    Returns:
        dict with classification, confidence, reasoning, retry_recommended
    """
    cache_key = (payment_data.get("error_code", ""), payment_data.get("payment_method", payment_data.get("method", "")))
    if cache_key in _classify_cache:
        return _classify_cache[cache_key].copy()

    # Try LLM first
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        try:
            result = _classify_with_llm(payment_data, key)
            _classify_cache[cache_key] = result
            return result
        except Exception as e:
            logger.warning(f"LLM classification failed, using fallback: {e}")

    # Fallback to rules-based
    result = _classify_with_rules(payment_data)
    _classify_cache[cache_key] = result
    return result


def _classify_with_llm(payment_data: dict, api_key: str) -> dict:
    """Use OpenAI LLM to classify the failure."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # Build context
    context = json.dumps(payment_data, indent=2)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify this payment failure:\n\n{context}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)

    # Ensure required fields
    result.setdefault("classification", "ambiguous")
    result.setdefault("confidence", 0.5)
    result.setdefault("reasoning", "LLM classification")
    result.setdefault("retry_recommended", result["classification"] == "transient")
    result.setdefault("retry_delay_minutes", 30)
    result.setdefault("max_retries", 2)

    return result


def _classify_with_rules(payment_data: dict) -> dict:
    """
    Rules-based fallback for failure classification.
    Uses error code patterns to determine transient vs permanent.
    """
    error_code = (payment_data.get("error_code") or "").upper()
    error_desc = (payment_data.get("error_description") or "").upper()
    method = (payment_data.get("method") or payment_data.get("payment_method") or "").lower()

    # Check transient patterns
    if error_code in TRANSIENT_ERROR_CODES:
        return {
            "classification": "transient",
            "confidence": 0.80,
            "reasoning": f"Error code '{error_code}' indicates infrastructure-side failure. "
                        f"This is typically a temporary issue (bank downtime, network timeout, or UPI rail degradation). "
                        f"Customer would likely succeed on retry.",
            "retry_recommended": True,
            "retry_delay_minutes": 30,
            "max_retries": 2,
        }

    # Check permanent patterns
    if error_code in PERMANENT_ERROR_CODES:
        return {
            "classification": "permanent",
            "confidence": 0.90,
            "reasoning": f"Error code '{error_code}' indicates customer-side failure. "
                        f"This is a permanent issue (insufficient funds, invalid card, or mandate revoked). "
                        f"Retry will not help — same issue will recur.",
            "retry_recommended": False,
            "retry_delay_minutes": 0,
            "max_retries": 0,
        }

    # Keyword-based fallback
    transient_keywords = ["timeout", "downtime", "network", "gateway", "server", "connection", "declined", "rail"]
    permanent_keywords = ["insufficient", "invalid", "expired", "revoked", "closed", "failed", "declined"]

    error_text = f"{error_code} {error_desc}"
    error_lower = error_text.lower()

    if any(kw in error_lower for kw in ["insufficient", "invalid", "expired", "revoked", "closed"]):
        return {
            "classification": "permanent",
            "confidence": 0.75,
            "reasoning": f"Error description contains permanent-failure keywords. "
                        f"Customer-side issue — retry not recommended.",
            "retry_recommended": False,
            "retry_delay_minutes": 0,
            "max_retries": 0,
        }

    if any(kw in error_lower for kw in ["timeout", "downtime", "network", "gateway", "server", "connection"]):
        return {
            "classification": "transient",
            "confidence": 0.70,
            "reasoning": f"Error description contains transient-failure keywords. "
                        f"Infrastructure issue — retry recommended.",
            "retry_recommended": True,
            "retry_delay_minutes": 30,
            "max_retries": 2,
        }

    # Ambiguous
    return {
        "classification": "ambiguous",
        "confidence": 0.40,
        "reasoning": f"Error code '{error_code}' does not match known transient or permanent patterns. "
                    f"Cannot determine with available data. Escalating to human.",
        "retry_recommended": False,
        "retry_delay_minutes": 0,
        "max_retries": 0,
    }
