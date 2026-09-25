from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import io
import re
from typing import Any, Dict, List, Optional
import pandas as pd
from pydantic import ValidationError

from app.domain.models.asset import Asset, AssetType, Currency, Sector
from app.domain.models.portfolio import Holding
from app.schemas.ingestion import RawHoldingRecord


@dataclass
class IngestionReport:
    """Report detailing the result of the ingestion and parsing process."""
    total_rows: int = 0
    valid_records_count: int = 0
    discarded_records_count: int = 0
    holdings: List[Holding] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        """True if all rows were parsed cleanly with at least one valid record."""
        return self.discarded_records_count == 0 and self.valid_records_count > 0

    @property
    def has_partial_errors(self) -> bool:
        """True if some rows succeeded while others failed."""
        return self.discarded_records_count > 0 and self.valid_records_count > 0


class BaseHoldingParser(ABC):
    """Abstract Base Class for tabular portfolio holding ingestion."""

    @abstractmethod
    def parse(self, content: bytes, file_format: str = "csv") -> IngestionReport:
        """Parses raw bytes from CSV or Excel into normalized domain holdings."""
        pass


class UniversalHoldingParser(BaseHoldingParser):
    """
    Universal, broker-agnostic parser for tabular holding reports.
    Provides adaptive fuzzy header resolution, Latin decimal parsing,
    asset classification inference, and row-level fault tolerance.
    """

    KNOWN_SOVEREIGN = (
        "AL30", "GD30", "AL29", "GD29", "AL35", "GD35", "AE38", "GD38",
        "AL41", "GD41", "GD46", "TX26", "TX28", "T2V4", "TV24", "TO26", "DICP", "PARP"
    )

    KNOWN_LOCAL_EQUITIES = {
        "GGAL", "YPFD", "PAMP", "BMA", "BBAR", "ALUA", "TXAR", "CRES",
        "TGSU2", "TECO2", "CEPU", "EDN", "TRAN", "LOMA", "MIRG", "COME",
        "BYMA", "VALO", "SUPV", "MORI", "BHIP", "BPAT", "DGCU2", "CGPA2",
        "BOLT", "AUSO", "OEST", "INVJ", "HAVA", "SEMI", "MOLI", "AGRO"
    }

    COLUMN_SYNONYMS = {
        "ticker": [
            "ticker", "simbolo", "especie", "codigo", "activo", "symbol",
            "cod_especie", "instrumento", "columna_cod", "columnacod"
        ],
        "quantity": [
            "cantidad", "nominales", "titulos", "shares", "quantity",
            "posicion", "cantidad_titulos", "columna_q", "columnaq"
        ],
        "purchase_price": [
            "precio compra", "preciocompra", "costo", "precio promedio",
            "preciopromedio", "precio_promedio", "ppc", "precio de compra",
            "purchase_price", "buy_price", "columna_p", "columnap"
        ],
        "current_price": [
            "precio actual", "precioactual", "cotizacion", "precio mercado",
            "preciomercado", "precio_mercado", "ult precio", "ult_precio",
            "current_price", "market_price", "precio"
        ],
        "currency": ["moneda", "divisa", "currency"],
        "market": ["mercado", "plaza", "market"],
        "asset_type": ["tipo", "tipo activo", "tipo_activo", "asset_type", "clase"]
    }

    def __init__(self, column_mapping: Optional[Dict[str, str]] = None) -> None:
        self.custom_mapping = column_mapping or {}

    def _normalize_col_name(self, col: str) -> str:
        c = str(col).lower().strip()
        c = re.sub(r"[\s_]+", "", c)
        return c

    def _resolve_columns(self, available_columns: List[str]) -> Dict[str, str]:
        resolved: Dict[str, str] = {}
        norm_available = {self._normalize_col_name(c): c for c in available_columns}

        # Apply custom overrides first
        for target, custom_name in self.custom_mapping.items():
            if custom_name in available_columns:
                resolved[target] = custom_name
            else:
                norm_c = self._normalize_col_name(custom_name)
                if norm_c in norm_available:
                    resolved[target] = norm_available[norm_c]

        # Match synonyms
        for target, synonyms in self.COLUMN_SYNONYMS.items():
            if target in resolved:
                continue
            for syn in synonyms:
                norm_syn = self._normalize_col_name(syn)
                if norm_syn in norm_available:
                    resolved[target] = norm_available[norm_syn]
                    break

        return resolved

    def _parse_numeric(self, val: Any) -> float:
        if val is None or pd.isna(val):
            raise ValueError("Valor nulo o vacío.")
        if isinstance(val, (int, float)):
            return float(val)

        s = str(val).strip()
        if not s:
            raise ValueError("Cadena numérica vacía.")

        # Latin formatting: 1.850,50 -> 1850.50
        if "." in s and "," in s:
            dot_idx = s.rfind(".")
            comma_idx = s.rfind(",")
            if comma_idx > dot_idx:
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s and "." not in s:
            s = s.replace(",", ".")

        return float(s)

    def _infer_asset_type(self, ticker: str, explicit_type: Optional[str] = None) -> AssetType:
        if explicit_type:
            up_type = explicit_type.strip().upper()
            for at in AssetType:
                if at.value == up_type:
                    return at

        t = ticker.strip().upper()
        if t in self.KNOWN_SOVEREIGN or (t.startswith(("AL", "GD", "AE", "TX", "TV", "TO", "T2")) and len(t) in (4, 5)):
            return AssetType.BOND_SOVEREIGN
        if t.startswith(("YMC", "IRC", "TLC", "MTC")):
            return AssetType.BOND_CORPORATE
        if t.startswith(("S", "LE", "BONCAP")) and len(t) > 3:
            return AssetType.TREASURY_BILL
        if t in self.KNOWN_LOCAL_EQUITIES:
            return AssetType.EQUITY

        return AssetType.CEDEAR

    def parse(self, content: bytes, file_format: str = "csv") -> IngestionReport:
        report = IngestionReport()

        try:
            if file_format.lower() in ("xlsx", "xls"):
                df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
            else:
                # CSV with delimiter sniffing (comma, semicolon, tab)
                sample = content[:4096].decode("utf-8", errors="ignore")
                sep = ";" if sample.count(";") > sample.count(",") else ","
                df = pd.read_csv(io.BytesIO(content), sep=sep, dtype=object)
        except Exception as e:
            report.total_rows = 1
            report.discarded_records_count = 1
            report.errors.append({
                "error_type": "FILE_READ_ERROR",
                "message": f"Error al decodificar el archivo: {str(e)}"
            })
            return report

        report.total_rows = len(df)
        if report.total_rows == 0:
            return report

        col_map = self._resolve_columns(list(df.columns))

        if "ticker" not in col_map or "quantity" not in col_map:
            report.discarded_records_count = report.total_rows
            report.errors.append({
                "error_type": "MAPPING_ERROR",
                "message": (
                    f"No se pudieron resolver las columnas obligatorias (ticker, cantidad). "
                    f"Columnas detectadas: {list(df.columns)}"
                )
            })
            return report

        for idx, row in df.iterrows():
            row_idx = int(idx) + 1
            try:
                raw_ticker = row.get(col_map["ticker"])
                if pd.isna(raw_ticker) or not str(raw_ticker).strip():
                    raise ValueError(f"Fila {row_idx}: Ticker ausente o nulo.")
                ticker_str = str(raw_ticker).strip().upper()

                raw_qty = row.get(col_map["quantity"])
                quantity = self._parse_numeric(raw_qty)

                purchase_price = 0.0
                if "purchase_price" in col_map and not pd.isna(row.get(col_map["purchase_price"])):
                    purchase_price = self._parse_numeric(row.get(col_map["purchase_price"]))

                current_price = purchase_price
                if "current_price" in col_map and not pd.isna(row.get(col_map["current_price"])):
                    current_price = self._parse_numeric(row.get(col_map["current_price"]))

                currency_val = "ARS"
                if "currency" in col_map and not pd.isna(row.get(col_map["currency"])):
                    c_str = str(row.get(col_map["currency"])).strip().upper()
                    if "USD" in c_str:
                        currency_val = "USD"

                market_val = None
                if "market" in col_map and not pd.isna(row.get(col_map["market"])):
                    market_val = str(row.get(col_map["market"])).strip()

                asset_type_val = None
                if "asset_type" in col_map and not pd.isna(row.get(col_map["asset_type"])):
                    asset_type_val = str(row.get(col_map["asset_type"])).strip()

                raw_record = RawHoldingRecord(
                    ticker=ticker_str,
                    quantity=quantity,
                    purchase_price=purchase_price,
                    current_price=current_price,
                    currency=currency_val,
                    market=market_val,
                    asset_type=asset_type_val,
                )

                inferred_asset_type = self._infer_asset_type(raw_record.ticker, raw_record.asset_type)
                holding_curr = Currency.USD if raw_record.currency == "USD" else Currency.ARS
                
                asset = Asset(
                    ticker=raw_record.ticker,
                    name=raw_record.ticker,
                    asset_type=inferred_asset_type,
                    currency=holding_curr,
                    sector=Sector.OTHER,
                )

                holding = Holding(
                    asset=asset,
                    quantity=raw_record.quantity,
                    average_buy_price=raw_record.purchase_price,
                    current_price=raw_record.current_price,
                    currency=holding_curr,
                )

                report.holdings.append(holding)
                report.valid_records_count += 1

            except (ValidationError, ValueError, Exception) as err:
                report.discarded_records_count += 1
                report.errors.append({
                    "row": row_idx,
                    "ticker": str(row.get(col_map.get("ticker", ""), "")),
                    "error_type": "ROW_VALIDATION_ERROR",
                    "detail": str(err)
                })

        return report
