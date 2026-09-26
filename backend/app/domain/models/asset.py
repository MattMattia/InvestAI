from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.domain.models.fx import Currency


class AssetType(str, Enum):
    """Classification of financial instruments supported by InvestAI."""
    EQUITY = "EQUITY"                      # Local Argentine Equities (Acciones)
    CEDEAR = "CEDEAR"                      # Argentine Depositary Receipts
    BOND_SOVEREIGN = "BOND_SOVEREIGN"      # Sovereign Government Bonds (ej. AL30, GD30)
    BOND_CORPORATE = "BOND_CORPORATE"      # Corporate Bonds / Obligaciones Negociables (ONs)
    TREASURY_BILL = "TREASURY_BILL"        # Short-term Treasury Bills (LECAPs, BONCAPs)
    CASH = "CASH"                          # Liquid cash balance


class Sector(str, Enum):
    """Economic and market sectors for exposure control."""
    TECHNOLOGY = "TECHNOLOGY"
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"
    ENERGY = "ENERGY"
    HEALTHCARE = "HEALTHCARE"
    CONSUMER_CYCLICAL = "CONSUMER_CYCLICAL"
    CONSUMER_DEFENSIVE = "CONSUMER_DEFENSIVE"
    INDUSTRIALS = "INDUSTRIALS"
    BASIC_MATERIALS = "BASIC_MATERIALS"
    UTILITIES = "UTILITIES"
    REAL_ESTATE = "REAL_ESTATE"
    COMMUNICATION_SERVICES = "COMMUNICATION_SERVICES"
    GOVERNMENT = "GOVERNMENT"              # For Sovereign Fixed Income
    CASH_EQUIVALENT = "CASH_EQUIVALENT"
    OTHER = "OTHER"


@dataclass(frozen=True)
class Asset:
    """
    Pure Domain representation of a financial asset.
    Framework-agnostic immutable Value Object.
    """
    ticker: str
    name: str
    asset_type: AssetType
    currency: Currency
    sector: Sector = Sector.OTHER
    country: str = "AR"
    cedear_ratio: Optional[float] = None
    underlying_ticker: Optional[str] = None

    @property
    def is_fixed_income(self) -> bool:
        """Returns True if the asset is a fixed income instrument (bonds, bills)."""
        return self.asset_type in {
            AssetType.BOND_SOVEREIGN,
            AssetType.BOND_CORPORATE,
            AssetType.TREASURY_BILL,
        }

    @property
    def is_equity(self) -> bool:
        """Returns True if the asset represents equity exposure (stocks, CEDEARs)."""
        return self.asset_type in {AssetType.EQUITY, AssetType.CEDEAR}

    @property
    def is_cedear(self) -> bool:
        """Returns True if the instrument is a CEDEAR with underlying ratio."""
        return self.asset_type == AssetType.CEDEAR and self.cedear_ratio is not None

