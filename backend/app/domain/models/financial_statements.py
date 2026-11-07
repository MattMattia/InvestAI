import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.fx import Currency


def clean_financial_float(v: Any) -> float | None:
    """
    Sanitizes corrupt, string-formatted, NaN or Infinite inputs into clean floats or None.
    Handles values like '$ 1,234.50', 'N/A', 'None', float('nan'), float('inf').
    """
    if v is None:
        return None
    if isinstance(v, int | float):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, str):
        cleaned = v.strip()
        if not cleaned or cleaned.upper() in {"N/A", "NONE", "NULL", "-", "NAN", "INF"}:
            return None
        # Remove currency symbols and formatting commas
        cleaned = re.sub(r"[$\s]", "", cleaned).replace(",", "")
        try:
            val = float(cleaned)
            return None if (math.isnan(val) or math.isinf(val)) else val
        except ValueError:
            return None
    return None


def safe_divide(
    numerator: float | None,
    denominator: float | None,
    default: float | None = None,
    precision: int = 4,
) -> float | None:
    """
    Safely executes floating-point division without throwing ZeroDivisionError, NaN, or Inf.
    Returns default if either operand is None or denominator is zero/near-zero.
    """
    if numerator is None or denominator is None:
        return default
    if (
        math.isnan(numerator)
        or math.isnan(denominator)
        or math.isinf(numerator)
        or math.isinf(denominator)
    ):
        return default
    if abs(denominator) < 1e-12:
        return default
    result = numerator / denominator
    return round(result, precision)


class IncomeStatementStandard(BaseModel):
    """
    Immutable standardized Income Statement compliant with OpenBB canonical fundamentals.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", arbitrary_types_allowed=True)

    revenue: float | None = Field(default=None, description="Total Revenue / Top-line sales")
    net_income: float | None = Field(default=None, description="Net Income / Bottom-line profit")
    eps: float | None = Field(default=None, description="Earnings Per Share (Basic)")
    diluted_eps: float | None = Field(default=None, description="Earnings Per Share (Diluted)")
    operating_income: float | None = Field(default=None, description="Operating Income / EBIT")
    gross_profit: float | None = Field(default=None, description="Gross Profit")
    ebitda: float | None = Field(default=None, description="EBITDA")
    period: str | None = Field(
        default="FY", description="Reporting period (e.g. 'FY2025', 'Q3-2025')"
    )
    fiscal_year: int | None = Field(default=None, description="Fiscal year")
    currency: Currency = Field(default=Currency.USD, description="Statement reporting currency")

    @model_validator(mode="before")
    @classmethod
    def sanitize_inputs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            if k in {
                "revenue",
                "net_income",
                "eps",
                "diluted_eps",
                "operating_income",
                "gross_profit",
                "ebitda",
            }:
                cleaned[k] = clean_financial_float(v)
            else:
                cleaned[k] = v
        return cleaned


class BalanceSheetStandard(BaseModel):
    """
    Immutable standardized Balance Sheet statement.
    Features automatic synthesis of net_debt and total_equity when composite fields exist.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", arbitrary_types_allowed=True)

    total_assets: float | None = Field(default=None, description="Total Assets")
    total_liabilities: float | None = Field(default=None, description="Total Liabilities")
    total_debt: float | None = Field(
        default=None, description="Total Debt (Short-term + Long-term)"
    )
    cash_and_equivalents: float | None = Field(default=None, description="Cash & Cash Equivalents")
    net_debt: float | None = Field(default=None, description="Net Debt = Total Debt - Cash")
    total_equity: float | None = Field(default=None, description="Total Stockholders Equity")
    current_assets: float | None = Field(default=None, description="Current Assets")
    current_liabilities: float | None = Field(default=None, description="Current Liabilities")
    period: str | None = Field(default="FY", description="Reporting period")
    fiscal_year: int | None = Field(default=None, description="Fiscal year")
    currency: Currency = Field(default=Currency.USD, description="Statement reporting currency")

    @model_validator(mode="before")
    @classmethod
    def sanitize_and_compute(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            if k in {
                "total_assets",
                "total_liabilities",
                "total_debt",
                "cash_and_equivalents",
                "net_debt",
                "total_equity",
                "current_assets",
                "current_liabilities",
            }:
                cleaned[k] = clean_financial_float(v)
            else:
                cleaned[k] = v

        # Deterministic auto-synthesis of Net Debt if omitted
        t_debt = cleaned.get("total_debt")
        cash = cleaned.get("cash_and_equivalents")
        if cleaned.get("net_debt") is None and t_debt is not None and cash is not None:
            cleaned["net_debt"] = round(t_debt - cash, 4)

        # Deterministic auto-synthesis of Total Equity if omitted
        assets = cleaned.get("total_assets")
        liabilities = cleaned.get("total_liabilities")
        if cleaned.get("total_equity") is None and assets is not None and liabilities is not None:
            cleaned["total_equity"] = round(assets - liabilities, 4)

        return cleaned


class CashFlowStandard(BaseModel):
    """
    Immutable standardized Cash Flow statement.
    Features automatic synthesis of free_cash_flow.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", arbitrary_types_allowed=True)

    operating_cash_flow: float | None = Field(default=None, description="Cash Flow from Operations")
    capital_expenditure: float | None = Field(
        default=None, description="Capital Expenditures (CapEx)"
    )
    free_cash_flow: float | None = Field(
        default=None, description="Free Cash Flow = Operating CF - CapEx"
    )
    financing_cash_flow: float | None = Field(default=None, description="Cash Flow from Financing")
    investing_cash_flow: float | None = Field(default=None, description="Cash Flow from Investing")
    period: str | None = Field(default="FY", description="Reporting period")
    fiscal_year: int | None = Field(default=None, description="Fiscal year")
    currency: Currency = Field(default=Currency.USD, description="Statement reporting currency")

    @model_validator(mode="before")
    @classmethod
    def sanitize_and_compute(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            if k in {
                "operating_cash_flow",
                "capital_expenditure",
                "free_cash_flow",
                "financing_cash_flow",
                "investing_cash_flow",
            }:
                cleaned[k] = clean_financial_float(v)
            else:
                cleaned[k] = v

        # Deterministic auto-synthesis of Free Cash Flow: Operating CF - abs(CapEx)
        ocf = cleaned.get("operating_cash_flow")
        capex = cleaned.get("capital_expenditure")
        if cleaned.get("free_cash_flow") is None and ocf is not None and capex is not None:
            cleaned["free_cash_flow"] = round(ocf - abs(capex), 4)

        return cleaned


class KeyMetricsStandard(BaseModel):
    """
    Immutable standardized valuation and financial health metrics with division-by-zero protection.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    pe_ratio: float | None = Field(default=None, description="Price to Earnings ratio (P/E)")
    pb_ratio: float | None = Field(default=None, description="Price to Book ratio (P/B)")
    peg_ratio: float | None = Field(default=None, description="Price/Earnings to Growth (PEG)")
    ev_to_ebitda: float | None = Field(default=None, description="Enterprise Value to EBITDA")
    current_ratio: float | None = Field(
        default=None, description="Current Assets / Current Liabilities"
    )
    debt_to_equity: float | None = Field(default=None, description="Total Debt / Total Equity")
    roe: float | None = Field(default=None, description="Return on Equity (Net Income / Equity)")

    @model_validator(mode="before")
    @classmethod
    def sanitize_inputs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for k, v in data.items():
            cleaned[k] = clean_financial_float(v)
        return cleaned


def compute_standard_metrics(
    current_price: float,
    income: IncomeStatementStandard,
    balance: BalanceSheetStandard,
    cash_flow: CashFlowStandard | None = None,
    shares_outstanding: float | None = None,
    earnings_growth_rate: float | None = None,
    enterprise_value: float | None = None,
) -> KeyMetricsStandard:
    """
    Deterministically computes KeyMetricsStandard from financial statements and market price.
    Guarantees zero-division safety and sanitizes edge cases.
    """
    price = clean_financial_float(current_price) or 0.0

    # P/E Ratio: Price / EPS (or Market Cap / Net Income)
    effective_eps = income.diluted_eps if income.diluted_eps is not None else income.eps
    pe = safe_divide(price, effective_eps) if (effective_eps and effective_eps > 0) else None

    # P/B Ratio: Price / Book Value Per Share (where BVPS = Total Equity / Shares)
    book_value_per_share = None
    if balance.total_equity is not None and shares_outstanding and shares_outstanding > 0:
        book_value_per_share = safe_divide(balance.total_equity, shares_outstanding)
    pb = (
        safe_divide(price, book_value_per_share)
        if (book_value_per_share and book_value_per_share > 0)
        else None
    )

    # PEG Ratio: (P/E) / Earnings Growth Rate (%)
    peg = None
    if pe is not None and earnings_growth_rate is not None and earnings_growth_rate > 0:
        # e.g., PE 20 / Growth 15% -> 20 / 15 = 1.3333
        peg = safe_divide(pe, earnings_growth_rate)

    # EV / EBITDA
    ev_ebitda = None
    if enterprise_value is not None and income.ebitda is not None:
        ev_ebitda = safe_divide(enterprise_value, income.ebitda)
    elif (
        enterprise_value is None
        and shares_outstanding
        and income.ebitda is not None
        and balance.net_debt is not None
    ):
        # Synthesize EV = Market Cap + Net Debt
        market_cap = price * shares_outstanding
        synthesized_ev = market_cap + balance.net_debt
        ev_ebitda = safe_divide(synthesized_ev, income.ebitda)

    # Current Ratio: Current Assets / Current Liabilities
    curr_ratio = safe_divide(balance.current_assets, balance.current_liabilities)

    # Debt to Equity: Total Debt / Total Equity
    d_to_e = safe_divide(balance.total_debt, balance.total_equity)

    # ROE: Net Income / Total Equity
    roe = safe_divide(income.net_income, balance.total_equity)

    return KeyMetricsStandard(
        pe_ratio=pe,
        pb_ratio=pb,
        peg_ratio=peg,
        ev_to_ebitda=ev_ebitda,
        current_ratio=curr_ratio,
        debt_to_equity=d_to_e,
        roe=roe,
    )
