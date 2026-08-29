"""
Base Engine — abstract base class for all recovery engines.
Defines the scan → diagnose → decide → execute → audit pattern.
"""

from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class EngineResult:
    """Result of a single engine run."""
    engine_name: str
    scanned: int = 0
    issues_found: int = 0
    amount_at_risk_inr: float = 0
    amount_recovered_inr: float = 0
    amount_pending_inr: float = 0
    escalated: int = 0
    issues: list = field(default_factory=list)
    escalations: list = field(default_factory=list)


class BaseEngine(ABC):
    """Abstract base class for all recovery engines."""

    def __init__(self, razorpay_client, boundary_config: dict, scan_run_id: str):
        self.razorpay = razorpay_client
        self.config = boundary_config
        self.scan_run_id = scan_run_id

    @abstractmethod
    def scan(self) -> list[dict]:
        """Scan Razorpay data and return potential issues."""
        pass

    @abstractmethod
    def diagnose(self, issue: dict) -> dict:
        """Diagnose the root cause of an issue using AI."""
        pass

    @abstractmethod
    def execute(self, issue: dict, diagnosis: dict) -> dict:
        """Execute recovery action within bounds."""
        pass

    def run(self) -> EngineResult:
        """
        Run the full scan → diagnose → execute → audit cycle.
        Returns aggregated results.
        """
        if not self.config.get("enabled", False):
            return EngineResult(engine_name=self.engine_name)

        result = EngineResult(engine_name=self.engine_name)

        # 1. SCAN
        issues = self.scan()
        result.scanned = len(issues)

        for issue in issues:
            result.issues_found += 1
            result.amount_at_risk_inr += issue.get("amount_inr", 0)

            # 2. DIAGNOSE
            diagnosis = self.diagnose(issue)

            # 3. DECIDE + EXECUTE
            outcome = self.execute(issue, diagnosis)

            if outcome.get("escalated"):
                result.escalated += 1
                result.escalations.append(outcome)
            elif outcome.get("recovered"):
                result.amount_recovered_inr += outcome.get("amount_recovered_inr", 0)
            elif outcome.get("pending"):
                result.amount_pending_inr += outcome.get("amount_pending_inr", 0)

            result.issues.append(outcome)

        return result

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Unique name for this engine."""
        pass
