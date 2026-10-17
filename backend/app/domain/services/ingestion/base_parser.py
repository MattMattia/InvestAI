"""
Abstract parsing interface, domain exceptions, and raw holding contracts
for broker report ingestion (Module 6.1 - Phase 1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from decimal import Decimal
from pathlib import PurePath
import re
from typing import Any
import unicodedata

from pydantic import Field, field_validator, model_validator

from app.schemas.envelope import BaseSchema

# ============================================================================
# Defensive Security & Resource Boundaries
# ============================================================================
MAX_REPORT_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB compressed/raw upload limit
MAX_DECOMPRESSED_XLSX_BYTES: int = 50 * 1024 * 1024  # 50 MB anti Zip-Bomb limit
MAX_COMPRESSION_RATIO: float = 100.0  # Anti Zip-Bomb compression ratio ceiling
MAX_REPORT_ROWS: int = 50_000  # Maximum holding rows per report
MAX_HEADER_SCAN_LINES: int = 50  # Maximum leading rows scanned to locate table header

_FORMULA_DANGEROUS_PREFIX_CHARS: str = "=+-@\t\r\n "
_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")
_HEADER_SEPARATOR_RE = re.compile(r"[-_/.,:;()\[\]]+")
_TRAILING_PUNCTUATION_RE = re.compile(r"[:.;,]+$")

# ============================================================================
# Canonical Column Header Alias Sets (Hook for Phase 2 SchemaDetector)
# ============================================================================
TICKER_HEADER_ALIASES: frozenset[str] = frozenset(
    {
        "ticker",
        "especie",
        "simbolo",
        "symbol",
        "activo",
        "instrumento",
        "codigo",
        "titulo",
        "descripcion especie",
        "denominacion",
        "nombre especie",
        "cod especie",
        "simb",
    }
)

QUANTITY_HEADER_ALIASES: frozenset[str] = frozenset(
    {
        "cantidad",
        "nominales",
        "cant",
        "quantity",
        "qty",
        "tenencia",
        "unidades",
        "vn",
        "valor nominal",
        "saldo nominal",
        "posicion",
        "cant nominales",
        "cantidad disponible",
    }
)

AVG_PRICE_HEADER_ALIASES: frozenset[str] = frozenset(
    {
        "precio promedio",
        "ppc",
        "avg price",
        "average price",
        "precio",
        "price",
        "costo promedio",
        "precio de compra",
        "precio promedio de compra",
        "precio promedio compra",
        "costo unitario",
        "precio compra",
        "precio pond",
        "prec prom compra",
    }
)

CURRENCY_HEADER_ALIASES: frozenset[str] = frozenset(
    {
        "moneda",
        "currency",
        "divisa",
        "moneda de liquidacion",
        "moneda emision",
        "moneda origen",
        "mon",
        "moneda liq",
    }
)

IGNORED_SUMMARY_TICKERS: frozenset[str] = frozenset(
    {
        "total",
        "totales",
        "subtotal",
        "subtotales",
        "total cartera",
        "total general",
        "saldo",
    }
)


# ============================================================================
# Typed Domain Exception Hierarchy
# ============================================================================
class ReportParsingError(Exception):
    """Base domain exception for broker report parsing failures."""


class UnsupportedReportFormatError(ReportParsingError):
    """Raised when the file extension or format is not supported."""


class EmptyReportError(ReportParsingError):
    """Raised when a report stream is empty or yields zero valid holdings."""


class CorruptedReportError(ReportParsingError):
    """Raised when a file stream is corrupted, binary-spoofed, or contains malicious payloads."""


class ReportSizeLimitExceededError(ReportParsingError):
    """Raised when a report exceeds byte size, compression ratio, or row count limits."""


class MissingRequiredColumnsError(ReportParsingError):
    """Raised when required canonical columns (ticker, quantity) cannot be found."""


# ============================================================================
# Header Normalization & Alias Resolution Helpers
# ============================================================================
def normalize_header_name(header: Any) -> str:
    """
    Normalize a column header or token into a canonical ASCII lowercase form.

    Strips null bytes, decomposes Unicode characters (NFKD) to remove diacritics,
    replaces hyphens/underscores/slashes/punctuation with spaces, and collapses whitespace.
    """
    if header is None:
        return ""
    raw_text = str(header).replace("\x00", "")
    decomposed = unicodedata.normalize("NFKD", raw_text)
    stripped_accents = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    lowered = stripped_accents.lower()
    separated = _HEADER_SEPARATOR_RE.sub(" ", lowered)
    return _WHITESPACE_COLLAPSE_RE.sub(" ", separated).strip()


def resolve_header_mapping(headers: Sequence[Any]) -> dict[str, int]:
    """
    Map canonical field names ('ticker', 'quantity', 'avg_price', 'currency', 'total_amount')
    to their best matching zero-based column index using `SchemaDetector`.
    """
    from app.domain.services.ingestion.schema_detector import SchemaDetector

    result = SchemaDetector().detect_schema(headers)
    return {
        field.value: col_mapping.column_index
        for field, col_mapping in result.mappings.items()
    }


def is_ignored_summary_ticker(raw_ticker: Any) -> bool:
    """
    Return True if the candidate ticker value corresponds to a table footer or summary row.
    """
    if raw_ticker is None:
        return True
    cleaned = _TRAILING_PUNCTUATION_RE.sub("", str(raw_ticker).strip())
    normalized = normalize_header_name(cleaned)
    return normalized in IGNORED_SUMMARY_TICKERS


def _sanitize_formula_prefix(value: str) -> str:
    """
    Mitigate CSV/Spreadsheet Formula Injection (CWE-1236) by stripping leading
    formula trigger characters ('=', '+', '-', '@', tabs, CR/LF) and quotes
    wrapping formula prefixes.
    """
    cleaned = value.strip()
    prev = None
    while cleaned and cleaned != prev:
        prev = cleaned
        cleaned = cleaned.lstrip(_FORMULA_DANGEROUS_PREFIX_CHARS)
        if len(cleaned) >= 2 and cleaned[0] in ("'", '"') and cleaned[1] in _FORMULA_DANGEROUS_PREFIX_CHARS:
            cleaned = cleaned[1:].lstrip(_FORMULA_DANGEROUS_PREFIX_CHARS)
    return cleaned.strip()


def _assert_no_null_bytes(value: Any, field_name: str) -> None:
    """Raise ValueError if a string or nested structure contains null bytes."""
    if isinstance(value, str) and "\x00" in value:
        raise ValueError(f"Null bytes are not permitted in '{field_name}'")


# ============================================================================
# Immutable Raw Holding DTO Contract
# ============================================================================
class RawHoldingRecord(BaseSchema):
    """
    Immutable intermediate record representing a single raw holding row
    extracted from a local broker statement (CSV or Excel).
    """

    row_number: int = Field(ge=1, description="1-based row number in the source report")
    raw_ticker: str = Field(
        min_length=1,
        max_length=64,
        description="Sanitized raw instrument ticker or symbol",
    )
    raw_quantity: str | Decimal | int | float = Field(
        description="Raw quantity or nominal units as extracted from the report"
    )
    raw_avg_price: str | Decimal | int | float | None = Field(
        default=None,
        description="Optional raw average purchase price (PPC)",
    )
    raw_currency: str | None = Field(
        default=None,
        max_length=16,
        description="Optional raw currency code or label",
    )
    raw_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Original row key-value mapping for downstream auditing and schema detection",
    )

    @field_validator("raw_ticker", mode="before")
    @classmethod
    def _validate_and_sanitize_ticker(cls, value: Any) -> str:
        if value is None:
            raise ValueError("raw_ticker cannot be None")
        text = str(value)
        _assert_no_null_bytes(text, "raw_ticker")
        sanitized = _sanitize_formula_prefix(text)
        if not sanitized:
            raise ValueError("Invalid or empty ticker after sanitization")
        return sanitized

    @field_validator("raw_currency", mode="before")
    @classmethod
    def _validate_and_sanitize_currency(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        _assert_no_null_bytes(text, "raw_currency")
        sanitized = _sanitize_formula_prefix(text)
        if not sanitized:
            return None
        return sanitized

    @field_validator("raw_quantity", mode="before")
    @classmethod
    def _validate_quantity(cls, value: Any) -> str | Decimal | int | float:
        if value is None or isinstance(value, bool):
            raise ValueError("raw_quantity is required and cannot be boolean or None")
        if isinstance(value, str):
            _assert_no_null_bytes(value, "raw_quantity")
            stripped = value.strip()
            if not stripped:
                raise ValueError("raw_quantity cannot be an empty string")
            return stripped
        if isinstance(value, (Decimal, int, float)):
            return value
        raise ValueError(f"Unsupported type for raw_quantity: {type(value).__name__}")

    @field_validator("raw_avg_price", mode="before")
    @classmethod
    def _validate_avg_price(cls, value: Any) -> str | Decimal | int | float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("raw_avg_price cannot be boolean")
        if isinstance(value, str):
            _assert_no_null_bytes(value, "raw_avg_price")
            stripped = value.strip()
            return stripped if stripped else None
        if isinstance(value, (Decimal, int, float)):
            return value
        raise ValueError(f"Unsupported type for raw_avg_price: {type(value).__name__}")

    @model_validator(mode="after")
    def _validate_raw_fields_null_bytes(self) -> RawHoldingRecord:
        for key, val in self.raw_fields.items():
            _assert_no_null_bytes(key, "raw_fields.key")
            if isinstance(val, str):
                _assert_no_null_bytes(val, f"raw_fields[{key}]")
        return self


# ============================================================================
# Abstract Base Parser & Strategy Factory
# ============================================================================
class BaseReportParser(ABC):
    """
    Abstract Strategy interface for broker report parsers.

    Subclasses must implement `parse_report` without blocking the ASGI event loop.
    """

    @abstractmethod
    async def parse_report(
        self, file_stream: bytes, filename: str
    ) -> list[RawHoldingRecord]:
        """
        Parse a raw binary report stream into a list of `RawHoldingRecord` items.
        """

    def validate_stream(self, file_stream: bytes, filename: str) -> None:
        """
        Enforce common perimeter invariants on filename and binary payload size.
        """
        if not isinstance(filename, str):
            raise UnsupportedReportFormatError("Filename must be a string")
        if "\x00" in filename:
            raise CorruptedReportError("Null bytes are not permitted in filename")
        if not filename.strip():
            raise UnsupportedReportFormatError("Filename cannot be empty")
        if not isinstance(file_stream, (bytes, bytearray)):
            raise TypeError("file_stream must be bytes or bytearray")
        if len(file_stream) == 0:
            raise EmptyReportError("Uploaded report stream is empty")
        if len(file_stream) > MAX_REPORT_SIZE_BYTES:
            raise ReportSizeLimitExceededError(
                f"Report size ({len(file_stream)} bytes) exceeds maximum limit "
                f"of {MAX_REPORT_SIZE_BYTES} bytes"
            )


def get_report_parser(filename: str) -> BaseReportParser:
    """
    Factory function returning the concrete `BaseReportParser` strategy
    matching the file extension of `filename`.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise UnsupportedReportFormatError("Filename must be a non-empty string")
    if "\x00" in filename:
        raise CorruptedReportError("Null bytes are not permitted in filename")

    ext = PurePath(filename.strip()).suffix.lower()
    if ext == ".csv":
        from app.domain.services.ingestion.csv_parser import CSVReportParser

        return CSVReportParser()
    if ext == ".xlsx":
        from app.domain.services.ingestion.excel_parser import ExcelReportParser

        return ExcelReportParser()

    raise UnsupportedReportFormatError(
        f"Unsupported report format '{ext or '<no extension>'}'. "
        "Only '.csv' and '.xlsx' files are supported."
    )

