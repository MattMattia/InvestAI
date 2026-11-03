"""
Data cleaning, monetary normalization, and schema validation pipeline
for broker report holdings (Module 6.2 - Phase 1).
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
import math
import re
from typing import Any
import unicodedata

from pydantic import Field

from app.domain.services.ingestion.base_parser import (
    RawHoldingRecord,
    _sanitize_formula_prefix,
)
from app.domain.services.market_data_provider import (
    BROKER_DESCRIPTION_TO_TICKER_MAP,
    CALIBRATED_10Y_METRICS_CATALOG,
    KNOWN_BOND_PREFIXES,
    KNOWN_CEDEAR_TICKERS,
)
from app.schemas.envelope import BaseSchema

# ============================================================================
# Defensive Security & Domain Boundaries
# ============================================================================
MAX_NUMERIC_STR_LENGTH: int = 32  # Mitigates Decimal exponent bomb DoS
HOLDING_DECIMAL_QUANTIZE: Decimal = Decimal("0.0001")
MIN_HOLDING_QUANTITY: Decimal = Decimal("0.0001")
MAX_HOLDING_QUANTITY: Decimal = Decimal("1000000000000")  # 10^12 ceiling
VALID_TICKER_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")

_LOCAL_EXCHANGE_SUFFIX_RE = re.compile(r"\.(BA|BCBA|RO|AR)$", re.IGNORECASE)
_CURRENCY_TOKEN_STRIP_RE = re.compile(
    r"(?:u\$s|us\$|ar\$|usd|ars|\$|%)", re.IGNORECASE
)
_THOUSANDS_COMMA_RE = re.compile(r"^\d{1,3}(,\d{3})+$")
_THOUSANDS_DOT_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")
_WHITESPACE_RE = re.compile(r"\s+")
_EMBEDDED_USD_HINT_RE = re.compile(
    r"(?:u\$s|us\$|\busd\b|\bdolar(?:es)?\b|\bmep\b|\bccl\b)", re.IGNORECASE
)

_EMPTY_PRICE_PLACEHOLDERS: frozenset[str] = frozenset(
    {"", "-", "--", "---", "n/a", "na", "s/d", "sd", "null", "none"}
)

_ARS_CURRENCY_ALIASES: frozenset[str] = frozenset(
    {
        "ars",
        "$",
        "peso",
        "pesos",
        "peso argentino",
        "pesos argentinos",
        "moneda local",
        "ar$",
        "ars $",
        "$ ars",
    }
)

_USD_CURRENCY_ALIASES: frozenset[str] = frozenset(
    {
        "usd",
        "u$s",
        "us$",
        "dolar",
        "dolares",
        "dolar estadounidense",
        "dolares estadounidenses",
        "dolar mep",
        "dolar ccl",
        "usd mep",
        "usd ccl",
        "u$s mep",
        "u$s ccl",
        "us$ mep",
        "us$ ccl",
        "mep",
        "ccl",
        "cable",
        "dolar billete",
        "dolar divisa",
    }
)


class CleaningErrorCode(str, Enum):
    """Taxonomic rejection codes for invalid holding records."""

    INVALID_TICKER = "INVALID_TICKER"
    NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY"
    ZERO_QUANTITY = "ZERO_QUANTITY"
    INVALID_NUMERIC_FORMAT = "INVALID_NUMERIC_FORMAT"
    INVALID_PRICE = "INVALID_PRICE"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"


class CleanHoldingRecord(BaseSchema):
    """
    Immutable, validated holding record ready for accounting checks and
    portfolio reconciliation.
    """

    row_number: int = Field(ge=1)
    ticker: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(gt=0, le=MAX_HOLDING_QUANTITY)
    avg_price: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="ARS", pattern=r"^(ARS|USD)$")
    raw_fields: dict[str, Any] = Field(default_factory=dict)


class InvalidHoldingRecord(BaseSchema):
    """Immutable audit record capturing a rejected holding row and its failure reason."""

    row_number: int = Field(ge=1)
    raw_ticker: str
    raw_quantity: Any
    error_code: CleaningErrorCode
    reason: str


class CleanReportResult(BaseSchema):
    """Immutable batch result returned by `DataCleaningPipeline.clean_records`."""

    valid_records: list[CleanHoldingRecord] = Field(default_factory=list)
    invalid_records: list[InvalidHoldingRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_valid(self) -> int:
        """Return total count of valid cleaned holding records."""
        return len(self.valid_records)

    @property
    def total_invalid(self) -> int:
        """Return total count of rejected holding records."""
        return len(self.invalid_records)

    @property
    def has_errors(self) -> bool:
        """Return True if at least one row was rejected during cleaning."""
        return len(self.invalid_records) > 0


def _strip_accents_lower(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.replace("\xa0", " "))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE_RE.sub(" ", stripped.lower()).strip()


class DataCleaningPipeline:
    """
    Stateless domain pipeline that normalizes tickers, currencies, and local/US
    monetary representations into strict `Decimal` contracts while isolating
    corrupted or negative rows.
    """

    def __init__(self, keep_ba_suffix: bool = False) -> None:
        self.keep_ba_suffix: bool = keep_ba_suffix

    @staticmethod
    def parse_decimal(value: Any) -> Decimal:
        """
        Parse an arbitrary numeric or formatted monetary value into a finite `Decimal`.

        Supports Argentine/European ('1.250.500,75') and US ('1,250,500.75')
        formats, currency prefixes/suffixes ('$', 'U$S', 'USD', 'ARS'), and
        accounting negative notations ('(1.250,50)' and '500-').
        """
        if value is None or isinstance(value, bool):
            raise ValueError("Cannot parse None or boolean as Decimal")

        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Non-finite Decimal value is not permitted")
            return value

        if isinstance(value, int):
            return Decimal(value)

        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Non-finite float value is not permitted")
            return Decimal(str(value))

        if not isinstance(value, str):
            raise ValueError(f"Unsupported numeric value type: {type(value).__name__}")

        raw_str = value.replace("\xa0", " ").strip()
        if not raw_str:
            raise ValueError("Empty numeric string")

        if len(raw_str) > MAX_NUMERIC_STR_LENGTH * 2:
            raise ValueError("Numeric string exceeds maximum defensive length")

        is_negative = False

        # Detect outer accounting parentheses before stripping currency tokens
        if raw_str.startswith("(") and raw_str.endswith(")"):
            is_negative = True
            raw_str = raw_str[1:-1].strip()

        # Remove currency symbols/codes and whitespace
        cleaned = _CURRENCY_TOKEN_STRIP_RE.sub("", raw_str)
        cleaned = _WHITESPACE_RE.sub("", cleaned)

        # Detect inner accounting parentheses e.g. "U$S (1.250,50)"
        if cleaned.startswith("(") and cleaned.endswith(")"):
            is_negative = True
            cleaned = cleaned[1:-1].strip()

        # Detect trailing minus e.g. "500-"
        if cleaned.endswith("-"):
            if is_negative:
                raise ValueError("Conflicting negative indicators in numeric string")
            is_negative = True
            cleaned = cleaned[:-1]

        # Detect leading sign e.g. "-1250,50" or "+1250,50"
        if cleaned.startswith("-"):
            if is_negative:
                raise ValueError("Conflicting negative indicators in numeric string")
            is_negative = True
            cleaned = cleaned[1:]
        elif cleaned.startswith("+"):
            cleaned = cleaned[1:]

        if not cleaned or len(cleaned) > MAX_NUMERIC_STR_LENGTH:
            raise ValueError(
                f"Invalid or oversized numeric token (length={len(cleaned)})"
            )

        lowered = cleaned.lower()
        if "nan" in lowered or "inf" in lowered:
            raise ValueError("NaN or Infinity literals are not permitted")

        normalized_str = DataCleaningPipeline._resolve_separators(cleaned)

        try:
            result = Decimal(normalized_str)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid numeric format: '{value}'") from exc

        if not result.is_finite():
            raise ValueError("Parsed Decimal is not finite")

        if is_negative and result != Decimal("0"):
            result = -result

        return result

    @staticmethod
    def _resolve_separators(token: str) -> str:
        """Resolve thousand and decimal separators deterministically."""
        has_dot = "." in token
        has_comma = "," in token

        if has_dot and has_comma:
            last_dot = token.rfind(".")
            last_comma = token.rfind(",")
            if last_comma > last_dot:
                # Argentine / European format: 1.250.500,75
                if token.count(",") > 1:
                    raise ValueError("Multiple decimal commas in number")
                return token.replace(".", "").replace(",", ".")
            else:
                # US / International format: 1,250,500.75
                if token.count(".") > 1:
                    raise ValueError("Multiple decimal dots in number")
                return token.replace(",", "")

        if has_comma:
            if token.count(",") > 1:
                if not _THOUSANDS_COMMA_RE.match(token):
                    raise ValueError("Malformed comma thousand separators")
                return token.replace(",", "")
            return token.replace(",", ".")

        if has_dot:
            if token.count(".") > 1:
                if not _THOUSANDS_DOT_RE.match(token):
                    raise ValueError("Malformed dot thousand separators")
                return token.replace(".", "")
            return token

        return token

    @classmethod
    def normalize_ticker(cls, raw_ticker: str, keep_ba_suffix: bool = False) -> str:
        """
        Normalize a broker instrument symbol into a canonical uppercase ticker.

        Strips local market suffixes ('.BA', '.BCBA', '.RO', '.AR') unless
        `keep_ba_suffix=True`, while preserving class suffixes like 'BRK.B'.
        """
        if not isinstance(raw_ticker, str):
            raise ValueError("Ticker must be a string")

        cleaned = _sanitize_formula_prefix(raw_ticker).upper()
        if not cleaned:
            raise ValueError("Ticker is empty after normalization")

        # Reject strings containing prohibited punctuation (e.g. '!', '@', '#', '$', '%', '?')
        if any(ch in cleaned for ch in "!@#$%^&*?=~`|\\<>"):
            raise ValueError(f"Invalid ticker format: '{raw_ticker}'")

        # Strip descriptive broker suffixes after ' - ', ' – ', or ' (' (e.g. 'GGAL - Grupo Galicia', 'AL30 (Bono)')
        for sep in (" - ", " – ", " — ", " ("):
            if sep in cleaned:
                cleaned = cleaned.split(sep, 1)[0].strip()

        # Map truncated or descriptive broker labels directly (e.g. Balanz 'CEDEAR N' -> 'NVDA')
        if cleaned in BROKER_DESCRIPTION_TO_TICKER_MAP:
            cleaned = BROKER_DESCRIPTION_TO_TICKER_MAP[cleaned]

        had_cedear_prefix = cleaned.startswith(("CEDEARS ", "CEDEAR "))

        # Strip common Argentine broker category prefixes (e.g. 'CEDEAR NVDA', 'BONO AL30')
        for prefix in ("CEDEARS ", "CEDEAR ", "ACCIONES ", "ACCION ", "BONOS ", "BONO ", "BONAR ", "GLOBAL ", "ON ", "LETRA ", "LECAP ", "FCI "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()

        if had_cedear_prefix and cleaned == "N":
            cleaned = "NVDA"

        # Strip common descriptive suffixes (e.g. 'AAPL CEDEAR N', 'NVDA CEDEAR', 'YPFD S.A.')
        for suffix in (" CEDEAR N", " CEDEAR", " S.A.I.C.", " S.A.", " SA", " INC.", " INC", " CORP.", " CORP"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip()

        # If multiple words remain (e.g. 'BONAR 2030 AL30'), extract known BYMA ticker token if present
        if " " in cleaned:
            for tok in cleaned.split():
                tok_clean = tok.strip(".,;()")
                if (
                    tok_clean in CALIBRATED_10Y_METRICS_CATALOG
                    or tok_clean in KNOWN_CEDEAR_TICKERS
                    or any(tok_clean.startswith(pref) for pref in KNOWN_BOND_PREFIXES)
                ):
                    cleaned = tok_clean
                    break

        had_local_suffix = False
        match = _LOCAL_EXCHANGE_SUFFIX_RE.search(cleaned)
        if match:
            had_local_suffix = True
            cleaned = cleaned[: match.start()]

        if not cleaned or cleaned.endswith((".", "-")) or ".." in cleaned:
            raise ValueError(f"Invalid ticker format: '{raw_ticker}'")

        if keep_ba_suffix and had_local_suffix:
            cleaned = f"{cleaned}.BA"

        if not VALID_TICKER_PATTERN.match(cleaned):
            raise ValueError(f"Invalid ticker format: '{raw_ticker}'")

        return cleaned

    @staticmethod
    def normalize_currency(raw_currency: str | None, default: str = "ARS") -> str:
        """
        Normalize local and international currency labels into canonical 'ARS' or 'USD'.
        """
        if raw_currency is None:
            return default

        cleaned = _strip_accents_lower(str(raw_currency))
        if not cleaned:
            return default

        if cleaned in _ARS_CURRENCY_ALIASES:
            return "ARS"
        if cleaned in _USD_CURRENCY_ALIASES:
            return "USD"

        raise ValueError(f"Unsupported currency: '{raw_currency}'")

    def clean_records(
        self, raw_records: Sequence[RawHoldingRecord]
    ) -> CleanReportResult:
        """
        Clean and validate a sequence of `RawHoldingRecord` items without aborting
        the batch when individual rows fail validation.
        """
        valid_records: list[CleanHoldingRecord] = []
        invalid_records: list[InvalidHoldingRecord] = []
        warnings: list[str] = []

        for raw in raw_records:
            # 1. Normalize & validate ticker
            try:
                ticker = self.normalize_ticker(
                    raw.raw_ticker, keep_ba_suffix=self.keep_ba_suffix
                )
            except ValueError as exc:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.INVALID_TICKER,
                        reason=str(exc),
                    )
                )
                continue

            # 2. Parse, quantize & validate quantity
            try:
                parsed_quantity = self.parse_decimal(raw.raw_quantity)
            except ValueError as exc:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.INVALID_NUMERIC_FORMAT,
                        reason=f"Invalid quantity '{raw.raw_quantity}': {exc}",
                    )
                )
                continue

            if parsed_quantity < Decimal("0"):
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.NEGATIVE_QUANTITY,
                        reason=f"Holding quantity must be positive (got {parsed_quantity})",
                    )
                )
                continue

            if parsed_quantity > MAX_HOLDING_QUANTITY:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.INVALID_NUMERIC_FORMAT,
                        reason=f"Quantity {parsed_quantity} exceeds maximum limit of {MAX_HOLDING_QUANTITY}",
                    )
                )
                continue

            quantity = parsed_quantity.quantize(
                HOLDING_DECIMAL_QUANTIZE, rounding=ROUND_HALF_UP
            )

            if quantity < MIN_HOLDING_QUANTITY:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.ZERO_QUANTITY,
                        reason=(
                            "Holding quantity cannot be zero or sub-pip "
                            f"(< {MIN_HOLDING_QUANTITY})"
                        ),
                    )
                )
                continue

            if quantity > MAX_HOLDING_QUANTITY:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.INVALID_NUMERIC_FORMAT,
                        reason=f"Quantity {quantity} exceeds maximum limit of {MAX_HOLDING_QUANTITY}",
                    )
                )
                continue

            # 3. Parse, quantize & validate optional average purchase price (PPC)
            avg_price: Decimal | None = None
            if raw.raw_avg_price is not None:
                raw_price_str = (
                    str(raw.raw_avg_price).replace("\xa0", " ").strip().lower()
                )
                if raw_price_str not in _EMPTY_PRICE_PLACEHOLDERS:
                    try:
                        parsed_price = self.parse_decimal(raw.raw_avg_price)
                    except ValueError as exc:
                        invalid_records.append(
                            InvalidHoldingRecord(
                                row_number=raw.row_number,
                                raw_ticker=raw.raw_ticker,
                                raw_quantity=raw.raw_quantity,
                                error_code=CleaningErrorCode.INVALID_PRICE,
                                reason=f"Invalid average price '{raw.raw_avg_price}': {exc}",
                            )
                        )
                        continue

                    if parsed_price < Decimal("0"):
                        invalid_records.append(
                            InvalidHoldingRecord(
                                row_number=raw.row_number,
                                raw_ticker=raw.raw_ticker,
                                raw_quantity=raw.raw_quantity,
                                error_code=CleaningErrorCode.INVALID_PRICE,
                                reason=f"Average purchase price cannot be negative (got {parsed_price})",
                            )
                        )
                        continue

                    quantized_price = parsed_price.quantize(
                        HOLDING_DECIMAL_QUANTIZE, rounding=ROUND_HALF_UP
                    )
                    if quantized_price == Decimal("0.0000"):
                        avg_price = None
                        warnings.append(
                            f"Row {raw.row_number} ({ticker}): zero or sub-pip average "
                            "purchase price was normalized to None."
                        )
                    else:
                        avg_price = quantized_price

            # 3b. If avg_price is None (e.g. PrecioCompra was 0 or absent in Balanz), fall back to 'Precio' column in raw_fields
            if avg_price is None and raw.raw_fields:
                for fallback_key in ("Precio", "precio", "PrecioCompra", "preciocompra"):
                    fb_val = raw.raw_fields.get(fallback_key)
                    if fb_val is not None and str(fb_val).strip().lower() not in _EMPTY_PRICE_PLACEHOLDERS:
                        try:
                            fb_dec = self.parse_decimal(fb_val).quantize(
                                HOLDING_DECIMAL_QUANTIZE, rounding=ROUND_HALF_UP
                            )
                            if fb_dec > Decimal("0"):
                                avg_price = fb_dec
                                break
                        except ValueError:
                            pass

            # 4. Normalize or infer currency
            inferred_default = self._infer_default_currency(
                raw.raw_avg_price, raw.raw_quantity
            )
            try:
                currency = self.normalize_currency(
                    raw.raw_currency, default=inferred_default
                )
            except ValueError as exc:
                invalid_records.append(
                    InvalidHoldingRecord(
                        row_number=raw.row_number,
                        raw_ticker=raw.raw_ticker,
                        raw_quantity=raw.raw_quantity,
                        error_code=CleaningErrorCode.UNSUPPORTED_CURRENCY,
                        reason=str(exc),
                    )
                )
                continue

            valid_records.append(
                CleanHoldingRecord(
                    row_number=raw.row_number,
                    ticker=ticker,
                    quantity=quantity,
                    avg_price=avg_price,
                    currency=currency,
                    raw_fields=dict(raw.raw_fields),
                )
            )

        return CleanReportResult(
            valid_records=valid_records,
            invalid_records=invalid_records,
            warnings=warnings,
        )

    @staticmethod
    def _infer_default_currency(raw_avg_price: Any, raw_quantity: Any) -> str:
        """
        Infer 'USD' when the currency column is missing but the price or quantity
        cell explicitly embeds a USD token (e.g. 'U$S 105,50' or 'USD 100').
        """
        for candidate in (raw_avg_price, raw_quantity):
            if isinstance(candidate, str) and _EMBEDDED_USD_HINT_RE.search(candidate):
                return "USD"
        return "ARS"

