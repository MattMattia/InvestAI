from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ValuationStatus(str, Enum):
    """Status indicator for accounting valuation multiples."""
    VALID = "VALID"                                # Valid multiples computed
    INDETERMINATE = "INDETERMINATE"                # Earnings <= 0 or inconsistent accounting denominator
    NOT_APPLICABLE = "NOT_APPLICABLE"              # Instrument type does not support multiples (e.g. Bonds, Cash)


@dataclass(frozen=True)
class ValuationMetrics:
    """
    Fundamental accounting valuation metrics (P/E, P/B, PEG).
    Implements deterministic exception handling for negative or null earnings (EPS <= 0).
    """
    ticker: str
    price: float
    eps: Optional[float] = None
    book_value_per_share: Optional[float] = None
    growth_rate_pct: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    status: ValuationStatus = ValuationStatus.VALID
    status_reason: Optional[str] = None

    @classmethod
    def calculate(
        cls,
        ticker: str,
        price: float,
        eps: Optional[float] = None,
        book_value_per_share: Optional[float] = None,
        growth_rate_pct: Optional[float] = None,
        is_equity: bool = True,
    ) -> "ValuationMetrics":
        """
        Deterministically calculates fundamental valuation multiples.
        Enforces specification rule: If EPS <= 0, multiples are INDETERMINATE.
        """
        if not is_equity:
            return cls(
                ticker=ticker,
                price=price,
                status=ValuationStatus.NOT_APPLICABLE,
                status_reason="Valuación contable no aplicable a instrumentos de renta fija o liquidez.",
            )

        if price <= 0:
            return cls(
                ticker=ticker,
                price=price,
                status=ValuationStatus.INDETERMINATE,
                status_reason="Precio del activo nulo o negativo.",
            )

        # 1. Evaluate Earnings Per Share (EPS) consistency
        if eps is None:
            computed_pe = None
            computed_peg = None
            pe_indeterminate = True
            indeterminate_reason = "Beneficio por acción (EPS) no disponible."
        elif eps <= 0:
            # Case EPS <= 0 (Specification F1.5 & Section 4.3: Manejo de Empresas con Pérdidas)
            computed_pe = None
            computed_peg = None
            pe_indeterminate = True
            indeterminate_reason = f"EPS nulo o negativo (EPS={eps}). Múltiplos P/E y PEG marcados como Indeterminados."
        else:
            computed_pe = round(price / eps, 4)
            pe_indeterminate = False
            indeterminate_reason = None

            # Calculate PEG if valid positive growth rate is provided
            if growth_rate_pct is not None and growth_rate_pct > 0:
                computed_peg = round(computed_pe / growth_rate_pct, 4)
            else:
                computed_peg = None

        # 2. Evaluate Price-to-Book (P/B)
        if book_value_per_share is not None and book_value_per_share > 0:
            computed_pb = round(price / book_value_per_share, 4)
        else:
            computed_pb = None

        final_status = (
            ValuationStatus.INDETERMINATE
            if pe_indeterminate
            else ValuationStatus.VALID
        )

        return cls(
            ticker=ticker,
            price=price,
            eps=eps,
            book_value_per_share=book_value_per_share,
            growth_rate_pct=growth_rate_pct,
            pe_ratio=computed_pe,
            pb_ratio=computed_pb,
            peg_ratio=computed_peg,
            status=final_status,
            status_reason=indeterminate_reason,
        )

