"""
Automatic schema detection and fuzzy column header normalization for local
broker statements (Module 6.1 - Phase 2).
"""
from __future__ import annotations

from collections.abc import Sequence
import difflib
from enum import Enum
import re
from typing import Any

from pydantic import Field

from app.domain.services.ingestion.base_parser import (
    MAX_HEADER_SCAN_LINES,
    normalize_header_name,
)
from app.schemas.envelope import BaseSchema

# ============================================================================
# Defensive Anti-DoS Constants
# ============================================================================
MIN_CONFIDENCE_THRESHOLD: float = 0.72
MAX_COLUMNS_TO_SCAN: int = 128
MAX_HEADER_LENGTH: int = 120

_NUMERIC_ONLY_RE = re.compile(r"^[+-]?(\d+([.,]\d+)?)$")


class CanonicalReportField(str, Enum):
    """Canonical semantic columns recognized across broker statements."""

    TICKER = "ticker"
    QUANTITY = "quantity"
    AVG_PRICE = "avg_price"
    CURRENCY = "currency"
    TOTAL_AMOUNT = "total_amount"


class DetectedColumnMapping(BaseSchema):
    """Immutable mapping between a raw report column and a canonical field."""

    canonical_field: CanonicalReportField
    raw_header: str
    normalized_header: str
    column_index: int = Field(ge=0)
    confidence_score: float = Field(ge=0.0, le=1.0)


class DetectedSchemaResult(BaseSchema):
    """Immutable result of running schema detection on a candidate header row."""

    header_row_index: int = Field(ge=0)
    mappings: dict[CanonicalReportField, DetectedColumnMapping] = Field(
        default_factory=dict
    )
    unmapped_headers: list[str] = Field(default_factory=list)

    def has_required_fields(self) -> bool:
        """Return True if both mandatory fields (TICKER and QUANTITY) are mapped."""
        return (
            CanonicalReportField.TICKER in self.mappings
            and CanonicalReportField.QUANTITY in self.mappings
        )

    def get_column_index(self, field: CanonicalReportField) -> int | None:
        """Return the zero-based column index mapped to `field`, or None."""
        mapping = self.mappings.get(field)
        return mapping.column_index if mapping is not None else None

    @property
    def total_confidence(self) -> float:
        """Return the sum of confidence scores across all mapped canonical fields."""
        return round(
            sum(m.confidence_score for m in self.mappings.values()),
            6,
        )


# ============================================================================
# Hierarchical Normalized Synonym Dictionaries (Argentine ALyCs & Standard)
# ============================================================================
_PRIMARY_SYNONYMS: dict[CanonicalReportField, frozenset[str]] = {
    CanonicalReportField.TICKER: frozenset(
        {
            "ticker",
            "especie",
            "simbolo",
            "symbol",
            "activo",
            "instrumento",
            "codigo",
            "titulo",
            "descripcion",
            "desc",
            "descripcion especie",
            "denominacion",
            "nombre especie",
            "cod especie",
            "codigo especie",
            "simb",
            "papel",
            "valor",
        }
    ),
    CanonicalReportField.QUANTITY: frozenset(
        {
            "cantidad",
            "nominales",
            "cant",
            "quantity",
            "qty",
            "tenencia",
            "unidades",
            "vn",
            "v n",
            "valor nominal",
            "saldo nominal",
            "posicion",
            "cant nominales",
            "cantidad disponible",
        }
    ),
    CanonicalReportField.AVG_PRICE: frozenset(
        {
            "precio promedio",
            "ppc",
            "p p c",
            "precio de compra",
            "precio promedio de compra",
            "precio promedio compra",
            "precio promedio compra ppc",
            "costo promedio",
            "avg price",
            "average price",
            "costo unitario",
            "precio compra",
            "preciocompra",
            "precio pond",
            "prec prom compra",
        }
    ),
    CanonicalReportField.CURRENCY: frozenset(
        {
            "moneda",
            "currency",
            "divisa",
            "moneda de liquidacion",
            "moneda liquidacion",
            "moneda emision",
            "moneda de emision",
            "moneda origen",
            "mon",
            "moneda liq",
        }
    ),
    CanonicalReportField.TOTAL_AMOUNT: frozenset(
        {
            "monto",
            "importe",
            "valor actual",
            "valoractual",
            "valor inicial",
            "valorinicial",
            "valuacion",
            "total",
            "monto total",
            "monto valorizado",
            "saldo valorizado",
            "valuacion actual",
            "valuacion al cierre",
            "importe total",
            "valor mercado",
        }
    ),
}

_AVG_PRICE_FALLBACK_SYNONYMS: frozenset[str] = frozenset({"precio", "price"})
_AVG_PRICE_FALLBACK_SCORE: float = 0.85

_AVG_PRICE_MARKET_BLACKLIST: frozenset[str] = frozenset(
    {
        "ultimo precio",
        "ult precio",
        "precio actual",
        "precio mercado",
        "precio de mercado",
        "cotizacion",
        "cotizacion actual",
        "precio cierre",
        "precio de cierre",
        "last price",
        "market price",
        "close price",
    }
)

_AVG_PRICE_BLACKLIST_TOKENS: frozenset[str] = frozenset(
    {
        "ultimo",
        "actual",
        "mercado",
        "cotizacion",
        "cierre",
        "market",
        "last",
        "close",
    }
)

_NON_HOLDING_NOISE_PREFIX_TOKENS: frozenset[str] = frozenset(
    {
        "tipo",
        "garantia",
        "porcentaje",
        "porcentajecartera",
        "fecha",
        "comision",
        "iva",
        "impuesto",
        "boleto",
        "numero",
        "nro",
        "arancel",
        "derecho",
        "plazo",
        "variacion",
        "ganancia",
        "gananciaporcentaje",
        "gananciapesos",
        "rendimiento",
        "rendimientoporcentaje",
        "rendimientopesos",
        "resultado",
        "comitente",
        "cuenta",
    }
)


class SchemaDetector:
    """
    Deterministic schema detector with exact, token-containment, and bounded
    fuzzy matching (`difflib.SequenceMatcher`) plus 1-to-1 greedy bipartite
    column assignment.
    """

    def __init__(self, min_confidence: float = MIN_CONFIDENCE_THRESHOLD) -> None:
        if not 0.0 < min_confidence <= 1.0:
            raise ValueError("min_confidence must be in (0.0, 1.0]")
        self.min_confidence: float = min_confidence

    def detect_schema(
        self,
        headers: Sequence[Any],
        header_row_index: int = 0,
    ) -> DetectedSchemaResult:
        """
        Inspect a single row of column headers and resolve a 1-to-1 mapping
        against `CanonicalReportField`.
        """
        if header_row_index < 0:
            raise ValueError("header_row_index must be >= 0")

        bounded_headers = list(headers[:MAX_COLUMNS_TO_SCAN])
        raw_headers: list[str] = []
        normalized_headers: list[str] = []

        for cell in bounded_headers:
            raw_str = "" if cell is None else str(cell).strip()
            truncated_raw = raw_str[:MAX_HEADER_LENGTH]
            raw_headers.append(truncated_raw)
            normalized_headers.append(
                normalize_header_name(truncated_raw)[:MAX_HEADER_LENGTH]
            )

        candidates: list[tuple[float, int, int, CanonicalReportField]] = []
        field_order = list(CanonicalReportField)

        for col_idx, norm_header in enumerate(normalized_headers):
            if not norm_header or _NUMERIC_ONLY_RE.match(norm_header):
                continue
            for field_priority, field in enumerate(field_order):
                score = self._score_header_against_field(norm_header, field)
                if score >= self.min_confidence:
                    candidates.append((score, -col_idx, -field_priority, field))

        # Sort descending by score, then ascending by col_idx and field_priority
        candidates.sort(reverse=True)

        assigned_fields: dict[CanonicalReportField, DetectedColumnMapping] = {}
        assigned_columns: set[int] = set()

        for score, neg_col_idx, _neg_field_prio, field in candidates:
            col_idx = -neg_col_idx
            if field in assigned_fields or col_idx in assigned_columns:
                continue
            assigned_fields[field] = DetectedColumnMapping(
                canonical_field=field,
                raw_header=raw_headers[col_idx],
                normalized_header=normalized_headers[col_idx],
                column_index=col_idx,
                confidence_score=round(score, 4),
            )
            assigned_columns.add(col_idx)

        unmapped_headers: list[str] = [
            raw_headers[idx]
            for idx in range(len(bounded_headers))
            if idx not in assigned_columns and raw_headers[idx]
        ]

        return DetectedSchemaResult(
            header_row_index=header_row_index,
            mappings=assigned_fields,
            unmapped_headers=unmapped_headers,
        )

    def find_best_header_row(
        self,
        rows_sample: Sequence[Sequence[Any]],
    ) -> DetectedSchemaResult | None:
        """
        Evaluate up to `MAX_HEADER_SCAN_LINES` candidate rows and return the
        `DetectedSchemaResult` with the richest valid schema mapping.
        """
        best_result: DetectedSchemaResult | None = None
        best_rank: tuple[int, float, int] | None = None

        scanned = 0
        for row_idx, row in enumerate(rows_sample):
            if not row or all(
                cell is None or not str(cell).strip() for cell in row[:MAX_COLUMNS_TO_SCAN]
            ):
                continue

            scanned += 1
            if scanned > MAX_HEADER_SCAN_LINES:
                break

            result = self.detect_schema(row, header_row_index=row_idx)
            if not result.has_required_fields():
                continue

            rank = (len(result.mappings), result.total_confidence, -row_idx)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_result = result

        return best_result

    @staticmethod
    def _score_header_against_field(
        normalized_header: str,
        field: CanonicalReportField,
    ) -> float:
        """
        Compute a deterministic confidence score in [0.0, 1.0] for matching
        `normalized_header` to `field`.
        """
        header = normalized_header[:MAX_HEADER_LENGTH].strip()
        if not header or _NUMERIC_ONLY_RE.match(header):
            return 0.0

        header_tokens = header.split()
        if not header_tokens:
            return 0.0

        # Guard against market-price vs average-purchase-price contamination
        if field == CanonicalReportField.AVG_PRICE:
            if header in _AVG_PRICE_MARKET_BLACKLIST:
                return 0.0
            if any(tok in _AVG_PRICE_BLACKLIST_TOKENS for tok in header_tokens):
                return 0.0

        primary_synonyms = _PRIMARY_SYNONYMS[field]

        # 1. Exact primary synonym match
        if header in primary_synonyms:
            return 1.0

        # 2. Exact fallback synonym match for AVG_PRICE
        if (
            field == CanonicalReportField.AVG_PRICE
            and header in _AVG_PRICE_FALLBACK_SYNONYMS
        ):
            return _AVG_PRICE_FALLBACK_SCORE

        # Prevent unrelated administrative/accounting columns from fuzzy-matching
        if header_tokens[0] in _NON_HOLDING_NOISE_PREFIX_TOKENS:
            return 0.0

        # Prevent quantity columns like "total nominales" from matching TOTAL_AMOUNT
        if field == CanonicalReportField.TOTAL_AMOUNT and any(
            qty_word in header_tokens
            for qty_word in ("nominales", "cantidad", "unidades", "tenencia")
        ):
            return 0.0

        if len(header) < 4:
            return 0.0

        best_score = 0.0
        header_token_set = set(header_tokens)

        # 3. Exact multi-token or single-token containment & fuzzy similarity
        candidate_synonyms = (
            primary_synonyms | _AVG_PRICE_FALLBACK_SYNONYMS
            if field == CanonicalReportField.AVG_PRICE
            else primary_synonyms
        )

        for syn in candidate_synonyms:
            if len(syn) < 4:
                continue

            is_fallback_syn = (
                field == CanonicalReportField.AVG_PRICE
                and syn in _AVG_PRICE_FALLBACK_SYNONYMS
            )
            max_allowed = _AVG_PRICE_FALLBACK_SCORE if is_fallback_syn else 1.0

            syn_tokens = syn.split()
            if len(syn_tokens) == 1:
                if syn in header_token_set:
                    containment_score = min(0.88, max_allowed)
                    if containment_score > best_score:
                        best_score = containment_score
            else:
                if all(tok in header_token_set for tok in syn_tokens):
                    containment_score = min(0.92, max_allowed)
                    if containment_score > best_score:
                        best_score = containment_score

            # Fuzzy similarity via SequenceMatcher
            # Guard: if multi-word synonym shares a generic suffix like "de liquidacion",
            # require first token similarity >= 0.65 so unrelated prefixes don't false-match.
            if len(syn_tokens) > 1 and len(header_tokens) > 1:
                head_ratio = difflib.SequenceMatcher(
                    None, header_tokens[0], syn_tokens[0]
                ).ratio()
                if head_ratio < 0.65 and syn_tokens[0] not in header_token_set:
                    continue

            ratio = difflib.SequenceMatcher(None, header, syn).ratio()
            capped_ratio = min(ratio, max_allowed)
            if capped_ratio > best_score:
                best_score = capped_ratio

        return best_score

