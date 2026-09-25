from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from app.domain.models.portfolio import Portfolio


class Severity(str, Enum):
    """Severity classification for deterministic risk violations."""
    INFO = "INFO"          # Informative notifications (e.g., target alignment)
    WARNING = "WARNING"    # Moderate deviation or non-critical risk threshold reached
    CRITICAL = "CRITICAL"  # Severe constraint breach (e.g. extreme concentration, huge drawdown)


@dataclass(frozen=True)
class RuleResult:
    """
    Deterministic evaluation outcome for a single rule or sub-rule.
    Provides complete auditability and traceability snapshot (F1.7).
    """
    rule_id: str
    rule_name: str
    passed: bool
    severity: Severity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseRiskRule(ABC):
    """
    Abstract Base Class for the Deterministic Strategy Pattern / Rule Engine (F1.6).
    Enforces the Open/Closed Principle for plugging new financial risk rules.
    """
    rule_id: str
    rule_name: str
    description: str

    @abstractmethod
    def evaluate(
        self,
        portfolio: Portfolio,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleResult]:
        """
        Executes deterministic checks against the portfolio.
        Returns a list of RuleResult objects documenting each evaluated constraint.
        """
        pass

