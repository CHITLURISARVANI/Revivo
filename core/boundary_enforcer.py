"""
Boundary Enforcer — the guardrail layer.
Checks every proposed action against merchant-set rules BEFORE execution.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

BOUNDARIES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "boundaries.json")


@dataclass
class BoundaryResult:
    allowed: bool
    reason: str
    escalate: bool
    threshold: Optional[float] = None
    current_value: Optional[float] = None


def load_boundaries() -> dict:
    """Load boundary configuration from JSON file."""
    with open(BOUNDARIES_PATH) as f:
        return json.load(f)


def save_boundaries(config: dict) -> None:
    """Save updated boundary configuration."""
    with open(BOUNDARIES_PATH, "w") as f:
        json.dump(config, f, indent=2)


def check_action(
    engine: str,
    action: str,
    amount: float,
    category: str = None,
    retry_count: int = 0,
) -> BoundaryResult:
    """
    Check if a proposed action is within merchant-set boundaries.
    Called BEFORE every execute step.

    Args:
        engine: Engine name (e.g., "capture_guardian")
        action: Action type (e.g., "capture", "retry", "contest", "reissue")
        amount: Amount in INR
        category: Dispute category (e.g., "fraud") — only for disputes
        retry_count: Current retry count — only for retries

    Returns:
        BoundaryResult with allowed=True if action is within bounds
    """
    config = load_boundaries()
    engine_config = config.get(engine, {})

    # 1. Engine enabled?
    if not engine_config.get("enabled", False):
        return BoundaryResult(
            allowed=False, reason="engine_disabled", escalate=True
        )

    # 2. Category restricted? (e.g., never auto-contest fraud)
    if category and category in engine_config.get("never_auto_contest_categories", []):
        return BoundaryResult(
            allowed=False, reason=f"category_restricted:{category}", escalate=True
        )

    # 3. Amount within threshold?
    threshold_key = f"{action}_threshold_inr"
    threshold = engine_config.get(threshold_key)
    if threshold is not None and amount > threshold:
        return BoundaryResult(
            allowed=False,
            reason="amount_exceeds_threshold",
            escalate=engine_config.get("escalate_above_threshold", True),
            threshold=threshold,
            current_value=amount,
        )

    # 4. Retry limit?
    if action == "retry":
        max_retries = engine_config.get("max_retries_per_payment", 2)
        if retry_count >= max_retries:
            return BoundaryResult(
                allowed=False, reason="max_retries_exceeded", escalate=False
            )

    # 5. Min amount for retry?
    if action == "retry":
        min_amount = engine_config.get("retry_only_above_inr", 0)
        if amount < min_amount:
            return BoundaryResult(
                allowed=False, reason="below_min_retry_amount", escalate=False
            )

    # All checks passed
    return BoundaryResult(allowed=True, reason="within_bounds", escalate=False)
