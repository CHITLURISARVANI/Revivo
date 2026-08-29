"""
Rules-based AI fallbacks used when OpenAI is unavailable.
Shared constants and re-exports for the AI reasoning layer.
"""

from ai.classifier import (
    TRANSIENT_ERROR_CODES,
    PERMANENT_ERROR_CODES,
    _classify_with_rules as classify_failure_fallback,
)
from ai.winnability import _score_with_rules as score_winnability_fallback
from ai.evidence_gen import _generate_with_template as generate_evidence_fallback
from ai.message_gen import _generate_with_template as generate_message_fallback

__all__ = [
    "TRANSIENT_ERROR_CODES",
    "PERMANENT_ERROR_CODES",
    "classify_failure_fallback",
    "score_winnability_fallback",
    "generate_evidence_fallback",
    "generate_message_fallback",
]
