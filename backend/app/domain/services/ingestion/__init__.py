"""
Domain ingestion services, format strategies, schema detection, data cleaning
pipeline, accounting integrity, and portfolio reconciliation exports
(Modules 6.1, 6.2 & 6.3).
"""

from app.domain.services.accounting_integrity import (
    MAX_COMPUTABLE_RATIO,
    MAX_RATIONAL_PE,
    RATIO_QUANTIZE_EXP,
    AccountingIntegrityService,
    AccountingRiskFlag,
    FinancialMetricsReport,
    FundamentalInputs,
    RatioStatus,
    RatioValue,
)
from app.domain.services.ingestion.base_parser import (
    AVG_PRICE_HEADER_ALIASES,
    CURRENCY_HEADER_ALIASES,
    IGNORED_SUMMARY_TICKERS,
    MAX_COMPRESSION_RATIO,
    MAX_DECOMPRESSED_XLSX_BYTES,
    MAX_HEADER_SCAN_LINES,
    MAX_REPORT_ROWS,
    MAX_REPORT_SIZE_BYTES,
    MAX_ZIP_ENTRIES,
    QUANTITY_HEADER_ALIASES,
    TICKER_HEADER_ALIASES,
    BaseReportParser,
    CorruptedReportError,
    EmptyReportError,
    MissingRequiredColumnsError,
    RawHoldingRecord,
    ReportParsingError,
    ReportSizeLimitExceededError,
    UnsupportedReportFormatError,
    get_report_parser,
    is_ignored_summary_ticker,
    normalize_header_name,
    resolve_header_mapping,
)
from app.domain.services.ingestion.csv_parser import CSVReportParser
from app.domain.services.ingestion.data_cleaning_pipeline import (
    HOLDING_DECIMAL_QUANTIZE,
    MAX_HOLDING_QUANTITY,
    MAX_NUMERIC_STR_LENGTH,
    MIN_HOLDING_QUANTITY,
    VALID_TICKER_PATTERN,
    CleanHoldingRecord,
    CleaningErrorCode,
    CleanReportResult,
    DataCleaningPipeline,
    InvalidHoldingRecord,
)
from app.domain.services.ingestion.excel_parser import ExcelReportParser
from app.domain.services.ingestion.schema_detector import (
    MAX_COLUMNS_TO_SCAN,
    MAX_HEADER_LENGTH,
    MIN_CONFIDENCE_THRESHOLD,
    CanonicalReportField,
    DetectedColumnMapping,
    DetectedSchemaResult,
    SchemaDetector,
)
from app.domain.services.portfolio_reconciliation import (
    RECONCILIATION_QUANTIZE,
    EmptyReconciliationSnapshotError,
    HoldingReconciliationEvent,
    PortfolioReconciliationError,
    PortfolioReconciliationService,
    ReconciliationAction,
    ReconciliationMode,
    ReconciliationPortfolioNotFoundError,
    ReconciliationReport,
)

__all__ = [
    "AVG_PRICE_HEADER_ALIASES",
    "CURRENCY_HEADER_ALIASES",
    "HOLDING_DECIMAL_QUANTIZE",
    "IGNORED_SUMMARY_TICKERS",
    "MAX_COLUMNS_TO_SCAN",
    "MAX_COMPRESSION_RATIO",
    "MAX_COMPUTABLE_RATIO",
    "MAX_DECOMPRESSED_XLSX_BYTES",
    "MAX_HEADER_LENGTH",
    "MAX_HEADER_SCAN_LINES",
    "MAX_HOLDING_QUANTITY",
    "MAX_NUMERIC_STR_LENGTH",
    "MAX_RATIONAL_PE",
    "MAX_REPORT_ROWS",
    "MAX_REPORT_SIZE_BYTES",
    "MAX_ZIP_ENTRIES",
    "MIN_CONFIDENCE_THRESHOLD",
    "MIN_HOLDING_QUANTITY",
    "QUANTITY_HEADER_ALIASES",
    "RATIO_QUANTIZE_EXP",
    "RECONCILIATION_QUANTIZE",
    "TICKER_HEADER_ALIASES",
    "VALID_TICKER_PATTERN",
    "AccountingIntegrityService",
    "AccountingRiskFlag",
    "BaseReportParser",
    "CSVReportParser",
    "CanonicalReportField",
    "CleanHoldingRecord",
    "CleanReportResult",
    "CleaningErrorCode",
    "CorruptedReportError",
    "DataCleaningPipeline",
    "DetectedColumnMapping",
    "DetectedSchemaResult",
    "EmptyReconciliationSnapshotError",
    "EmptyReportError",
    "ExcelReportParser",
    "FinancialMetricsReport",
    "FundamentalInputs",
    "HoldingReconciliationEvent",
    "IngestionReportSummary",
    "InvalidHoldingRecord",
    "MissingRequiredColumnsError",
    "PortfolioReconciliationError",
    "PortfolioReconciliationService",
    "RatioStatus",
    "RatioValue",
    "RawHoldingRecord",
    "ReconciliationAction",
    "ReconciliationMode",
    "ReconciliationPortfolioNotFoundError",
    "ReconciliationReport",
    "ReportParsingError",
    "ReportSizeLimitExceededError",
    "SchemaDetector",
    "UnsupportedReportFormatError",
    "get_report_parser",
    "is_ignored_summary_ticker",
    "normalize_header_name",
    "resolve_header_mapping",
]


def __getattr__(name: str):
    if name == "IngestionReportSummary":
        from app.schemas.ingestion import IngestionReportSummary

        return IngestionReportSummary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
