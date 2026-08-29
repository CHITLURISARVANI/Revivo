"""
AI Message Generator — generates personalized Hinglish recovery messages
for abandoned checkouts and failed payment retries.
Uses LLM when available, falls back to template-based generation.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

MESSAGE_SYSTEM_PROMPT = """You are writing a recovery message for an Indian e-commerce customer
who abandoned their checkout or had a failed payment.

Write in Hinglish (Hindi + English mix) — natural, friendly, slightly urgent but not pushy.

Rules:
- Use the customer's name if available
- Mention the exact order amount
- Mention what they ordered (if available)
- Include the payment link
- Create urgency (limited stock, offer expiring, etc.)
- Keep it under 160 characters for SMS
- Use 1-2 emojis max

Return JSON:
{
    "message": "the Hinglish message",
    "tone": "friendly_urgent",
    "language": "hinglish",
    "channel": "sms"
}"""


def generate_recovery_message(order_data: dict, customer_data: dict, payment_link_url: str, api_key: str = None) -> dict:
    """
    Generate a personalized Hinglish recovery message.

    Args:
        order_data: dict with amount, items, order_id
        customer_data: dict with name, phone, email
        payment_link_url: Razorpay payment link URL
        api_key: OpenAI API key

    Returns:
        dict with message, tone, language, channel
    """
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        try:
            return _generate_with_llm(order_data, customer_data, payment_link_url, key)
        except Exception as e:
            logger.warning(f"LLM message generation failed, using fallback: {e}")

    return _generate_with_template(order_data, customer_data, payment_link_url)


def _generate_with_llm(order_data: dict, customer_data: dict, payment_link_url: str, api_key: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    context = json.dumps({
        "order": order_data,
        "customer": customer_data,
        "payment_link": payment_link_url,
    }, indent=2)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": MESSAGE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate a recovery message:\n\n{context}"},
        ],
        temperature=0.3,  # slight creativity for natural language
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    result.setdefault("message", _generate_with_template(order_data, customer_data, payment_link_url)["message"])
    result.setdefault("tone", "friendly_urgent")
    result.setdefault("language", "hinglish")
    result.setdefault("channel", "sms")
    return result


def _generate_with_template(order_data: dict, customer_data: dict, payment_link_url: str) -> dict:
    """Template-based Hinglish message generation."""
    name = customer_data.get("name", "Bhai")
    amount = order_data.get("amount_inr", order_data.get("amount", 0))
    # Amount is already in INR (not paise) — if it looks like paise (>1000), convert
    if amount and amount > 100000:  # likely in paise if > ₹1000
        amount = amount / 100

    items = order_data.get("items", order_data.get("description", "your order"))

    message = (
        f"{name}, aapka ₹{amount:,.0f} ka order pending hai 🛒 "
        f"{items} — 10 min mein complete karo: {payment_link_url} "
        f"Order confirm ho jayega aur kal hi ship hoga!"
    )

    return {
        "message": message,
        "tone": "friendly_urgent",
        "language": "hinglish",
        "channel": "sms",
    }
