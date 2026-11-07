from dataclasses import dataclass, field
from enum import Enum

from app.domain.models.asset import Asset, AssetType, Currency, Sector


class InvestorProfile(str, Enum):
    """Risk tolerance profile capturing investor preferences (F1.2)."""

    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


@dataclass
class Holding:
    """
    Representation of an individual asset position inside a portfolio.
    """

    asset: Asset
    quantity: float
    average_buy_price: float
    current_price: float
    currency: Currency = Currency.ARS
    target_weight_pct: float | None = None

    @property
    def total_cost(self) -> float:
        """Total historical acquisition cost."""
        return self.quantity * self.average_buy_price

    @property
    def market_value(self) -> float:
        """Current market valuation in holding currency."""
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        """Nominal unrealized profit and loss."""
        return self.market_value - self.total_cost

    @property
    def unrealized_pnl_pct(self) -> float:
        """Percentage unrealized return on investment."""
        if self.total_cost <= 0:
            return 0.0
        return round((self.unrealized_pnl / self.total_cost) * 100.0, 2)


@dataclass
class Portfolio:
    """
    Pure domain representation of an investment portfolio.
    Provides deterministic aggregation and weight calculations.
    """

    id: str | None = None
    name: str = "Portafolio Principal"
    investor_profile: InvestorProfile = InvestorProfile.MODERATE
    holdings: list[Holding] = field(default_factory=list)
    cash_balance_ars: float = 0.0
    cash_balance_usd: float = 0.0

    def total_value_ars(self, fx_ccl: float = 1.0) -> float:
        """
        Consolidates the entire portfolio market value in ARS (Pesos).
        Converts USD holdings and cash using the implicit/reference CCL rate.
        """
        total = self.cash_balance_ars + (self.cash_balance_usd * fx_ccl)
        for h in self.holdings:
            val = h.market_value
            if h.currency in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP}:
                val *= fx_ccl
            total += val
        return round(total, 2)

    def total_value_usd(self, fx_ccl: float = 1.0) -> float:
        """
        Consolidates the entire portfolio market value in USD.
        """
        total_ars = self.total_value_ars(fx_ccl)
        if fx_ccl <= 0:
            return 0.0
        return round(total_ars / fx_ccl, 2)

    def get_holding_weights(self, fx_ccl: float = 1.0) -> dict[str, float]:
        """
        Calculates the percentage weight (%) of each holding relative to total portfolio value.
        """
        tot_ars = self.total_value_ars(fx_ccl)
        if tot_ars <= 0:
            return {h.asset.ticker: 0.0 for h in self.holdings}

        weights: dict[str, float] = {}
        for h in self.holdings:
            val_ars = h.market_value
            if h.currency in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP}:
                val_ars *= fx_ccl
            weight = (val_ars / tot_ars) * 100.0
            weights[h.asset.ticker] = round(weight, 2)

        return weights

    def get_sector_allocation(self, fx_ccl: float = 1.0) -> dict[Sector, float]:
        """
        Calculates percentage allocation by economic sector.
        """
        tot_ars = self.total_value_ars(fx_ccl)
        if tot_ars <= 0:
            return {}

        sector_totals: dict[Sector, float] = {}
        for h in self.holdings:
            val_ars = h.market_value
            if h.currency in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP}:
                val_ars *= fx_ccl
            sec = h.asset.sector
            sector_totals[sec] = sector_totals.get(sec, 0.0) + val_ars

        return {sec: round((val / tot_ars) * 100.0, 2) for sec, val in sector_totals.items()}

    def get_asset_type_allocation(self, fx_ccl: float = 1.0) -> dict[AssetType, float]:
        """
        Calculates percentage allocation by asset type (Equity, CEDEAR, Bonds, etc.).
        """
        tot_ars = self.total_value_ars(fx_ccl)
        if tot_ars <= 0:
            return {}

        type_totals: dict[AssetType, float] = {}
        for h in self.holdings:
            val_ars = h.market_value
            if h.currency in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP}:
                val_ars *= fx_ccl
            t = h.asset.asset_type
            type_totals[t] = type_totals.get(t, 0.0) + val_ars

        return {t: round((val / tot_ars) * 100.0, 2) for t, val in type_totals.items()}

    @property
    def fixed_income_weight_pct(self) -> float:
        """Convenience calculation for fixed income exposure."""
        alloc = self.get_asset_type_allocation()
        return round(
            alloc.get(AssetType.BOND_SOVEREIGN, 0.0)
            + alloc.get(AssetType.BOND_CORPORATE, 0.0)
            + alloc.get(AssetType.TREASURY_BILL, 0.0),
            2,
        )

    @property
    def equity_weight_pct(self) -> float:
        """Convenience calculation for total equity exposure (Acciones + CEDEARs)."""
        alloc = self.get_asset_type_allocation()
        return round(
            alloc.get(AssetType.EQUITY, 0.0) + alloc.get(AssetType.CEDEAR, 0.0),
            2,
        )
